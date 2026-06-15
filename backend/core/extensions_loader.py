"""extensions/ 디렉터리를 스캔해 각 확장 툴의 API 라우터와 정적 SPA 를 마운트한다.

메인 앱과 분리된 '확장 시스템' 인프라다. 이 로더 자체는 evaluator 같은 개별 툴을
모르며, 컨벤션(``<tool>/backend/router.py`` 의 ``get_router()`` + ``<tool>/frontend/dist``)
만 따른다. 따라서:

- ``extensions/<tool>/`` 폴더 하나를 통째로 지워도 로더는 빈손으로 no-op → 앱 부팅 무영향.
- 새 툴 추가도 컨벤션만 지키면 메인 앱 코드 수정이 불필요(이 로더가 자동 발견).

frozen EXE 에서도 동작하도록, 라우터 모듈은 name-import 가 아니라 파일 경로
적재(``spec_from_file_location``)로 불러온다. PyInstaller onefile 은 datas 를
``MEIPASS`` 디스크로 추출하므로 ``router.py`` 를 파일에서 읽어 실행할 수 있고,
그 안의 ``from core... import`` 같은 절대 import 는 frozen 번들이 만족시킨다.
"""

from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path
from types import ModuleType

from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles

from core.config import _project_root

logger = logging.getLogger(__name__)

# 확장 툴 디렉터리 안의 고정 컨벤션 경로.
_ROUTER_MODULE_RELPATH = ("backend", "router.py")
_STATIC_DIST_RELPATH = ("frontend", "dist")
_ROUTER_FACTORY_NAME = "get_router"
# 정적 SPA 마운트 prefix. 예: extensions/evaluator → /ext/evaluator
_STATIC_MOUNT_PREFIX = "/ext"
# 확장 메타데이터 매니페스트 (선택) — 패널 런처 드롭다운의 표시 이름/설명/아이콘.
_MANIFEST_FILENAME = "extension.json"


def _extensions_dir() -> Path:
    """확장 루트 디렉터리. frozen=``MEIPASS/extensions``, dev=``PROJECT_ROOT/extensions``."""
    return _project_root() / "extensions"


def load_extensions(app: FastAPI) -> None:
    """``extensions/*/`` 를 스캔해 각 툴의 라우터(/api/ext/<name>)와 정적 dist(/ext/<name>)를 마운트한다.

    반드시 메인 SPA catch-all 라우트보다 **먼저** 호출돼야 한다 — Starlette 는 등록
    순서로 매칭하므로 ``/api/ext/*``·``/ext/*`` 가 ``/{path:path}`` 폴백에 잡히면 안 된다.

    Args:
        app: 라우터/정적 마운트를 추가할 FastAPI 인스턴스.
    """
    ext_root = _extensions_dir()
    if not ext_root.exists():
        return

    for tool_dir in sorted(_iter_tool_dirs(ext_root)):
        try:
            _mount_extension(app, tool_dir)
        except Exception as exc:  # noqa: BLE001 — 확장 1개의 실패가 앱 전체 부팅을 막지 않게 격리
            logger.warning("확장 '%s' 로드 건너뜀: %s", tool_dir.name, exc)


def _iter_tool_dirs(ext_root: Path) -> list[Path]:
    """확장 루트 하위의 툴 디렉터리 목록. ``_``/``.`` 접두 폴더는 제외(내부용)."""
    return [
        path
        for path in ext_root.iterdir()
        if path.is_dir() and not path.name.startswith(("_", "."))
    ]


def list_available_extensions() -> list[dict[str, str]]:
    """패널 런처가 띄울 수 있는 확장(UI 가 있는) 목록을 반환한다.

    ``frontend/dist`` 가 있는 확장만 포함한다 — 패널은 정적 SPA 를 iframe 으로
    임베드하므로, 라우터만 있고 화면이 없는 확장은 런처에 띄울 수 없다. 각 확장 루트의
    선택적 ``extension.json`` 매니페스트(``{name, description, icon}``)로 표시 이름을
    꾸미고, 없으면 폴더명을 그대로 쓴다.

    Returns:
        ``{tool, name, description, icon}`` 딕셔너리 목록 (tool 이름순 정렬).
    """
    ext_root = _extensions_dir()
    if not ext_root.exists():
        return []

    out: list[dict[str, str]] = []
    for tool_dir in sorted(_iter_tool_dirs(ext_root)):
        dist_dir = tool_dir.joinpath(*_STATIC_DIST_RELPATH)
        if not dist_dir.is_dir():
            continue
        try:
            out.append(_read_extension_meta(tool_dir))
        except Exception as exc:  # noqa: BLE001 — 매니페스트 손상이 목록 전체를 막지 않게 격리
            logger.warning("확장 '%s' 메타 읽기 실패: %s", tool_dir.name, exc)
            out.append(
                {
                    "tool": tool_dir.name,
                    "name": tool_dir.name,
                    "description": "",
                    "icon": "",
                }
            )
    return out


def _read_extension_meta(tool_dir: Path) -> dict[str, str]:
    """확장 루트의 ``extension.json`` 을 읽어 메타데이터를 구성한다 (없으면 폴더명 폴백)."""
    name = tool_dir.name
    meta = {"tool": name, "name": name, "description": "", "icon": ""}
    manifest = tool_dir / _MANIFEST_FILENAME
    if not manifest.is_file():
        return meta

    raw = json.loads(manifest.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        for key in ("name", "description", "icon"):
            value = raw.get(key)
            if isinstance(value, str) and value:
                meta[key] = value
    return meta


def _mount_extension(app: FastAPI, tool_dir: Path) -> None:
    """한 확장 툴의 라우터와 정적 SPA 를 마운트한다(있는 것만)."""
    name = tool_dir.name
    _mount_router(app, name, tool_dir.joinpath(*_ROUTER_MODULE_RELPATH))
    _mount_static(app, name, tool_dir.joinpath(*_STATIC_DIST_RELPATH))


def _mount_router(app: FastAPI, name: str, router_py: Path) -> None:
    """``backend/router.py`` 의 ``get_router()`` 결과를 앱에 include 한다."""
    if not router_py.is_file():
        return

    module = _load_module_from_path(f"ext_{name}_router", router_py)
    factory = getattr(module, _ROUTER_FACTORY_NAME, None)
    if factory is None:
        logger.warning(
            "확장 '%s': %s() 미정의 — API 라우터 마운트 생략",
            name,
            _ROUTER_FACTORY_NAME,
        )
        return

    router = factory()
    if not isinstance(router, APIRouter):
        logger.warning(
            "확장 '%s': %s() 가 APIRouter 가 아님", name, _ROUTER_FACTORY_NAME
        )
        return

    app.include_router(router)
    logger.info("확장 '%s': API 라우터 마운트", name)


def _mount_static(app: FastAPI, name: str, dist_dir: Path) -> None:
    """빌드된 SPA(``frontend/dist``)를 ``/ext/<name>`` 로 정적 서빙한다.

    ``html=True`` 로 디렉터리 요청 시 ``index.html`` 을 돌려줘 SPA 루트 진입을 처리한다.
    """
    if not dist_dir.is_dir():
        return

    mount_path = f"{_STATIC_MOUNT_PREFIX}/{name}"
    app.mount(
        mount_path,
        StaticFiles(directory=dist_dir, html=True),
        name=f"ext_{name}_static",
    )
    logger.info("확장 '%s': 정적 SPA 마운트 → %s", name, mount_path)


def _load_module_from_path(module_name: str, path: Path) -> ModuleType:
    """파일 경로에서 모듈을 적재한다 (name-import 불필요 — frozen 에서도 동작).

    flat(점 없는) 모듈명으로 적재해 패키지-상대 import 부재 문제를 피한다. 확장
    모듈은 ``core.*``·``api.*`` 등 호스트가 이미 번들한 절대 import 만 사용해야 한다.

    Args:
        module_name: ``sys.modules`` 에 등록할 flat 모듈명.
        path: 적재할 ``.py`` 파일 절대 경로.

    Returns:
        실행된 모듈 객체.

    Raises:
        ImportError: spec/loader 생성에 실패할 때.
    """
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"모듈 spec 생성 실패: {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
