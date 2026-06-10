"""세션별 산출물 저장 경로를 관리하는 유틸리티.

산출물(이미지·JSON·Markdown 등)은 다음 구조로 저장된다::

    RESULT_DIR / {sanitized_title}-{client_id[:8]} / {YYYYMMDD-HHmmss} / <files>

harness.run_turn 이 턴 시작 시 ``set_session_context()`` 를 호출해 세션 메타를
contextvars 에 설정하면, 이후 도구·프로바이더 코드에서 ``artifact_slot()`` 만
호출해 타임스탬프 슬롯 경로를 받을 수 있다.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config import RESULT_DIR

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 세션 컨텍스트 — harness.run_turn 진입 시 설정
# ---------------------------------------------------------------------------

_current_client_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "_current_client_id", default=""
)
_current_session_title: contextvars.ContextVar[str] = contextvars.ContextVar(
    "_current_session_title", default=""
)
# 같은 턴 내 save_artifact 가 여러 번 호출되어도 단일 타임스탬프 슬롯을 재사용하기
# 위해 캐싱한다. set_session_context() 가 호출될 때마다 리셋되어 새 턴은 새 슬롯을
# 할당받는다.
_current_turn_slot: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "_current_turn_slot", default=None
)

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

_ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_TITLE_MAX_LEN = 30
_RESULT_PREFIX = "result/"
# 세션 산출물 목록(manifest). 세션 루트(타임스탬프 폴더의 형제)에 위치한다.
_MANIFEST_FILENAME = "_artifacts.jsonl"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def set_session_context(client_id: str, session_title: str) -> None:
    """harness 가 턴 시작 시 호출 — 이후 artifact_slot() 등에서 참조한다.

    매 호출마다 turn_slot 캐시도 리셋되므로 새 턴은 새 타임스탬프 폴더를
    얻고, 같은 턴 내 save_artifact 가 반복 호출되면 동일 폴더에 모인다.
    """
    _current_client_id.set(client_id)
    _current_session_title.set(session_title)
    _current_turn_slot.set(None)


def current_client_id() -> str:
    """현재 turn 의 client_id 반환. set_session_context 전에는 빈 문자열."""
    return _current_client_id.get()


def current_session_title() -> str:
    """현재 turn 의 session_title 반환. set_session_context 전에는 빈 문자열."""
    return _current_session_title.get()


def sanitize_title(raw: str, max_len: int = _TITLE_MAX_LEN) -> str:
    """Windows/POSIX 안전한 폴더명으로 변환한다.

    Args:
        raw: 원본 세션 제목 (한글·영문·공백 포함 가능).
        max_len: 결과 문자열 최대 길이.

    Returns:
        파일시스템에 안전한 문자열. 빈 값이면 ``"untitled"`` 반환.
    """
    cleaned = _ILLEGAL_CHARS.sub("", raw).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        return "untitled"
    return cleaned[:max_len]


def session_dir_name(
    client_id: str | None = None, session_title: str | None = None
) -> str:
    """``{sanitized_title}-{uuid[:8]}`` 형태 폴더 이름을 반환한다.

    인자를 생략하면 현재 contextvars 값을 사용한다.
    """
    cid = client_id or _current_client_id.get()
    title = session_title if session_title is not None else _current_session_title.get()
    safe_title = sanitize_title(title)
    short_id = cid[:8] if cid else "00000000"
    return f"{safe_title}-{short_id}"


def session_dir(client_id: str | None = None, session_title: str | None = None) -> Path:
    """세션 레벨 디렉터리 Path 를 반환한다. 디스크 생성은 하지 않는다."""
    return RESULT_DIR / session_dir_name(client_id, session_title)


def artifact_slot(
    client_id: str | None = None, session_title: str | None = None
) -> Path:
    """타임스탬프 산출물 슬롯을 디스크에 생성하고 Path 를 반환한다.

    호출할 때마다 새 ``YYYYMMDD-HHmmss`` 폴더가 만들어진다 (append-only).
    같은 시나리오 안에서 관련 산출물을 한 폴더에 모으려면 반환값을 캐싱해 재사용.
    """
    parent = session_dir(client_id, session_title)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    slot = parent / ts
    slot.mkdir(parents=True, exist_ok=True)
    return slot


def resolve_result_path(source: str) -> tuple[Path | None, str | None]:
    """'result/...' 상대 경로를 RESULT_DIR 기준의 검증된 절대 Path 로 환원한다.

    frozen EXE 에서는 CWD 가 프로젝트 루트가 아니므로, 산출물 파일 접근은
    반드시 이 함수를 거쳐 RESULT_DIR 절대 기준으로 일원화한다. 확장자 제약은
    호출자가 검사한다 (예: display_chart 의 '.spec.json').

    Args:
        source: save_artifact 류 도구가 반환한 'result/...' 형식 경로.

    Returns:
        (절대 Path, None) 성공 / (None, 에러 메시지) 실패.
    """
    normalized = source.strip().replace("\\", "/")

    if not normalized.startswith(_RESULT_PREFIX):
        return None, (
            f"'result/...' 형식 경로만 허용됩니다: {source!r}. "
            "save_artifact 가 반환한 경로를 그대로 전달하세요."
        )

    rel = normalized[len(_RESULT_PREFIX) :]
    if not rel or ".." in rel:
        return None, f"허용되지 않는 산출물 경로: {source!r}"

    target = RESULT_DIR / rel
    # 문자열 검사를 통과해도 드라이브 절대경로 결합 등으로 벗어날 수 있어
    # resolve 후 containment 를 한 번 더 확인한다 (이중 방어).
    try:
        target.resolve().relative_to(RESULT_DIR.resolve())
    except ValueError:
        return None, f"산출물 디렉터리 밖 경로는 참조할 수 없습니다: {source!r}"

    if not target.exists():
        return None, f"산출물 파일을 찾을 수 없습니다: {source!r}"

    return target, None


def to_result_relative(absolute: Path) -> str:
    """RESULT_DIR 하위 절대경로를 'result/...' 상대 표기로 변환한다.

    Args:
        absolute: RESULT_DIR 하위의 절대 Path.

    Returns:
        'result/<session>/<ts>/<file>' 형식 문자열.

    Raises:
        ValueError: absolute 가 RESULT_DIR 하위가 아닐 때.
    """
    return _RESULT_PREFIX + absolute.relative_to(RESULT_DIR).as_posix()


def iter_session_dirs(client_id: str) -> list[Path]:
    """client_id 에 속한 모든 세션 산출물 디렉터리를 반환한다.

    세션 제목이 변경되면 같은 client_id 라도 ``{title}-{cid8}`` 폴더가 여러 개
    생기므로, 제목과 무관하게 cid8 접미사 매칭으로 전부 수집한다.
    (다른 세션 제목이 우연히 '-{cid8}' 로 끝날 가능성은 uuid hex 8자 특성상
    무시 가능한 수준으로 본다.)

    Args:
        client_id: 세션 식별자 (UUID).

    Returns:
        이름 순으로 정렬된 세션 디렉터리 Path 목록. 없으면 빈 리스트.
    """
    if not client_id:
        return []
    suffix = f"-{client_id[:8]}"
    if not RESULT_DIR.exists():
        return []
    return sorted(
        path
        for path in RESULT_DIR.glob(f"*{suffix}")
        if path.is_dir() and path.name.endswith(suffix)
    )


def append_manifest_entry(entry: dict[str, Any]) -> None:
    """현재 세션 manifest(_artifacts.jsonl)에 산출물 기록 한 줄을 추가한다.

    manifest 는 히스토리 윈도우 밖이나 세션 복원 후에도 LLM 이 과거 산출물을
    재발견할 수 있게 하는 디스크 진실원천이다. 기록 실패가 save_artifact 본체를
    실패시키면 안 되므로 OSError 는 warning 으로 삼킨다 (best-effort).

    Args:
        entry: 직렬화 가능한 산출물 메타 (ts/path/kind/description 등).
    """
    target = session_dir() / _MANIFEST_FILENAME
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("manifest 기록 실패: %s (%s)", target, exc)


def read_manifest_entries(client_id: str, limit: int) -> list[dict[str, Any]]:
    """client_id 의 모든 세션 폴더 manifest 를 병합해 최신순으로 반환한다.

    세션 rename 으로 cid8 폴더가 여러 개여도 전부 병합한다. manifest 가 비어
    있거나 없으면 디스크를 직접 스캔해 fallback 목록을 만든다 (parquet 메타는
    읽지 않아 비용을 통제). 손상된 JSON 라인은 건너뛴다.

    Args:
        client_id: 세션 식별자.
        limit: 반환할 최대 항목 수.

    Returns:
        ts 내림차순으로 정렬된 산출물 메타 목록 (최대 limit 개).
    """
    entries: list[dict[str, Any]] = []
    for sdir in iter_session_dirs(client_id):
        manifest = sdir / _MANIFEST_FILENAME
        if not manifest.exists():
            continue
        try:
            for line in manifest.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # 손상 라인은 무시 — 나머지는 살린다.
        except OSError as exc:
            logger.warning("manifest 읽기 실패: %s (%s)", manifest, exc)

    if not entries:
        entries = _scan_disk_artifacts(client_id)

    entries.sort(key=lambda e: str(e.get("ts", "")), reverse=True)
    return entries[:limit]


def _scan_disk_artifacts(client_id: str) -> list[dict[str, Any]]:
    """manifest 가 없을 때 디스크를 직접 스캔한 fallback 산출물 목록.

    파생물(charts.json 등)·내부 폴더(_namespace)·manifest 파일 자신은 제외하며,
    parquet 메타데이터는 읽지 않는다 (비용 통제 — list_artifacts 가 필요 시 읽음).
    """
    derived = {"charts.json", "charts.filter.json", _MANIFEST_FILENAME}
    ts_pattern = re.compile(r"^\d{8}-\d{6}$")
    scanned: list[dict[str, Any]] = []
    for sdir in iter_session_dirs(client_id):
        for ts_dir in sdir.iterdir():
            if not ts_dir.is_dir() or not ts_pattern.match(ts_dir.name):
                continue
            for f in ts_dir.iterdir():
                if not f.is_file() or f.name in derived:
                    continue
                scanned.append(
                    {
                        "ts": ts_dir.name,
                        "path": to_result_relative(f),
                        "kind": f.suffix.lstrip("."),
                        "description": "",
                    }
                )
    return scanned


def turn_slot() -> Path:
    """현재 턴의 산출물 슬롯 — 같은 턴 내 호출은 동일 폴더를 반환한다.

    save_artifact 처럼 LLM 이 같은 턴 안에서 여러 파일을 저장할 때 한 폴더에
    모으기 위한 캐시. 새 턴 진입은 ``set_session_context()`` 가 캐시를
    무효화하므로 호출 즉시 새 타임스탬프 폴더가 할당된다.

    Returns:
        타임스탬프 슬롯 디렉토리 Path. 이미 디스크에 생성되어 있다.
    """
    cached = _current_turn_slot.get()
    if cached is not None:
        return cached
    slot = artifact_slot()
    _current_turn_slot.set(slot)
    return slot


def peek_turn_slot() -> Path | None:
    """현재 턴 슬롯 캐시를 조회만 한다 (없으면 None, 생성하지 않음).

    ``turn_slot()`` 과 달리 슬롯을 새로 만들지 않으므로, 슬롯이 실제로 쓰였는지
    여부를 부수효과 없이 확인할 수 있다.
    """
    return _current_turn_slot.get()


def adopt_turn_slot(slot: Path) -> None:
    """외부에서 만든 슬롯을 현재 턴 캐시로 채택한다.

    ``loop.run_in_executor`` 는 contextvars 를 전파하지 않으므로, 워커 스레드에서
    만든 슬롯은 메인 코루틴의 turn-slot 캐시에 반영되지 않는다. exec_code 의
    artifact_dir() 헬퍼가 스레드에서 슬롯을 생성했을 때 이 함수로 캐시에 역동기화해,
    같은 턴의 후속 save_artifact 가 동일 폴더를 공유하도록 한다.

    Args:
        slot: 채택할 타임스탬프 슬롯 Path.
    """
    _current_turn_slot.set(slot)
