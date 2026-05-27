"""세션별 산출물 저장 경로를 관리하는 유틸리티.

산출물(이미지·JSON·Markdown 등)은 다음 구조로 저장된다::

    RESULT_DIR / {sanitized_title}-{client_id[:8]} / {YYYYMMDD-HHmmss} / <files>

harness.run_turn 이 턴 시작 시 ``set_session_context()`` 를 호출해 세션 메타를
contextvars 에 설정하면, 이후 도구·프로바이더 코드에서 ``artifact_slot()`` 만
호출해 타임스탬프 슬롯 경로를 받을 수 있다.
"""

from __future__ import annotations

import contextvars
import re
from datetime import datetime
from pathlib import Path

from core.config import RESULT_DIR

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
