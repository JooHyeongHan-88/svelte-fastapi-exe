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
