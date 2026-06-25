"""tracer 확장 — 디버그 트레이스 JSONL 뷰어의 API 라우터.

``backend/agent/debug/trace.py`` 가 dev 환경에서 턴마다 기록한 트레이스 파일
(``result/<session>/_trace/<turn_id>.jsonl``)을 읽어 프론트 타임라인 뷰에 제공한다.
``extensions/`` 컨벤션상 호스트의 extensions_loader 가 파일 경로로 적재하므로,
**패키지-상대 import 없이** 호스트가 이미 번들한 절대 import 만 사용한다.

엔드포인트(prefix ``/api/ext/tracer``):

- ``GET /sessions``      : ``_trace/`` 폴더가 있는 세션 목록
- ``GET /turns?session=`` : 그 세션의 턴 트레이스 파일 목록(시간 역순)
- ``GET /trace?path=``    : 한 턴 트레이스 JSONL 을 파싱한 이벤트 배열

경로 해석은 ``core.result_store.resolve_result_path`` (RESULT_DIR 절대 기준 +
containment) 로 일원화하고, 보안 포스처는 호스트 Origin 가드를 재사용한다.
"""

import json
import logging
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import require_local_origin
from core.config import RESULT_DIR
from core.result_store import resolve_result_path, to_result_relative

logger = logging.getLogger(__name__)

_TRACE_DIRNAME = "_trace"
_TURN_START_KIND = "turn_start"
_PREVIEW_MAX_CHARS = 80
# turn_start 는 한 턴의 첫 이벤트라 앞쪽 몇 줄만 읽으면 된다 (대용량 provider_request 줄 회피).
_PREVIEW_SCAN_LINES = 10

router = APIRouter(
    prefix="/api/ext/tracer",
    dependencies=[Depends(require_local_origin)],
    tags=["ext:tracer"],
)


def _trace_dir_for(session: str) -> Path:
    """세션 폴더명 → 검증된 ``<session>/_trace`` 절대 경로 (containment 보장).

    Raises:
        HTTPException: 경로 구분자·`..` 등으로 RESULT_DIR 를 벗어나면 400.
    """
    if not session or "/" in session or "\\" in session or ".." in session:
        raise HTTPException(status_code=400, detail=f"잘못된 세션 이름: {session!r}")
    trace_dir = RESULT_DIR / session / _TRACE_DIRNAME
    try:
        trace_dir.resolve().relative_to(RESULT_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="허용되지 않는 경로") from None
    return trace_dir


@router.get("/sessions")
def list_sessions() -> list[dict[str, Any]]:
    """``_trace/`` 가 있는 세션을 최신 트레이스 순으로 반환한다."""
    if not RESULT_DIR.exists():
        return []
    out: list[dict[str, Any]] = []
    for session_dir in RESULT_DIR.iterdir():
        if not session_dir.is_dir():
            continue
        trace_dir = session_dir / _TRACE_DIRNAME
        if not trace_dir.is_dir():
            continue
        turns = sorted(trace_dir.glob("*.jsonl"))
        if not turns:
            continue
        latest = max(t.stat().st_mtime for t in turns)
        out.append(
            {
                "session": session_dir.name,
                "turns": len(turns),
                "latest": latest,
            }
        )
    out.sort(key=lambda s: s["latest"], reverse=True)
    return out


def _turn_preview(turn_path: Path) -> str:
    """턴 트레이스의 turn_start 이벤트에서 사용자 메시지 앞부분을 추출한다.

    turn_start 는 한 턴의 첫 이벤트라 앞쪽 몇 줄만 스캔하면 된다. 개행·연속 공백은 한 칸으로
    정리하고, 공백뿐이거나 부재면 빈 문자열을 돌려 프론트가 턴 ID 로 폴백하게 한다.

    Args:
        turn_path: 턴 트레이스 JSONL 파일 경로.

    Returns:
        정리·절단된 미리보기 문자열. 추출 실패 시 빈 문자열.
    """
    try:
        with turn_path.open("r", encoding="utf-8") as fh:
            for _, line in zip(range(_PREVIEW_SCAN_LINES), fh):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("kind") != _TURN_START_KIND:
                    continue
                raw = event.get("payload", {}).get("user_message", "")
                collapsed = " ".join(str(raw).split())
                return collapsed[:_PREVIEW_MAX_CHARS]
    except OSError:
        return ""
    return ""


@router.get("/turns")
def list_turns(
    session: Annotated[str, Query(description="세션 폴더명")],
) -> list[dict[str, Any]]:
    """세션의 턴 트레이스 파일 목록을 최신순으로 반환한다."""
    trace_dir = _trace_dir_for(session)
    if not trace_dir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for turn in trace_dir.glob("*.jsonl"):
        stat = turn.stat()
        out.append(
            {
                "name": turn.stem,
                "path": to_result_relative(turn),
                "mtime": stat.st_mtime,
                "size": stat.st_size,
                "preview": _turn_preview(turn),
            }
        )
    out.sort(key=lambda t: t["mtime"], reverse=True)
    return out


@router.get("/trace")
def read_trace(
    path: Annotated[str, Query(description="result/<session>/_trace/<turn>.jsonl")],
) -> dict[str, Any]:
    """한 턴 트레이스 JSONL 을 파싱해 이벤트 배열로 반환한다.

    손상된 줄(잘림 등)은 건너뛰되 개수를 함께 보고한다.
    """
    target, error = resolve_result_path(path)
    if error or target is None:
        raise HTTPException(
            status_code=404, detail=error or "트레이스를 찾을 수 없습니다."
        )
    if target.suffix.lower() != ".jsonl" or target.parent.name != _TRACE_DIRNAME:
        raise HTTPException(status_code=400, detail="트레이스 JSONL 경로가 아닙니다.")

    events: list[dict[str, Any]] = []
    skipped = 0
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            skipped += 1
    return {"events": events, "skipped": skipped}


def get_router() -> APIRouter:
    """extensions_loader 가 호출하는 라우터 팩토리."""
    return router
