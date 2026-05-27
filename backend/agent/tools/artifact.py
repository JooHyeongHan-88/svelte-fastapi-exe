"""산출물 저장 도구 — LLM 이 직접 마크다운/JSON/텍스트 파일을 디스크에 기록한다.

display_markdown 등 시각화 도구는 디스크에 사전 존재하는 파일만 표시할 수 있다.
LLM 이 작성한 리포트·분석 데이터를 사용자에게 영속적으로 남기려면 이 도구를
호출해 ``result/<session>/<ts>/<filename>`` 경로에 먼저 저장한 뒤, 반환된 path 를
시각화 도구에 전달하는 표준 체인을 사용한다.

같은 턴 내 여러 번 호출되면 ``core.result_store.turn_slot()`` 캐시 덕분에 같은
타임스탬프 폴더에 모이도록 설계되어 있다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated, Literal

from agent.models import ToolResult
from agent.registries.tools import register_tool
from core.config import RESULT_DIR
from core.result_store import turn_slot

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 상수 — kind ↔ 허용 확장자 매핑
# ---------------------------------------------------------------------------

_KIND_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "markdown": (".md", ".markdown"),
    "json": (".json",),
    "text": (".txt",),
}

# 디스크 절대경로를 프론트엔드/시각화 도구가 사용하는 상대 경로 형태로 환원할 때
# 사용되는 접두사. display_markdown 등은 'result/...' 형태를 받는다.
_RESULT_PREFIX = "result/"


# ---------------------------------------------------------------------------
# 내부 검증 헬퍼
# ---------------------------------------------------------------------------


def _validate_filename(filename: str) -> str | None:
    """filename 안전성 검사. 문제가 있으면 LLM 에 회신할 오류 메시지를 반환한다.

    Returns:
        오류 메시지(있으면) 또는 None.
    """
    if not filename or not filename.strip():
        return "filename 이 비어 있습니다."

    if "/" in filename or "\\" in filename:
        return f"filename 에 경로 구분자가 포함되었습니다: {filename!r}. 단순 파일명만 허용합니다."

    if ".." in filename:
        return f"filename 에 '..' 가 포함되었습니다: {filename!r}. 경로 escape 는 금지됩니다."

    # Windows 절대경로(예: 'C:\\evil.txt') 방어 — 위에서 백슬래시는 이미 잡혔지만
    # 'C:foo' 같은 드라이브-상대 표기도 차단한다.
    if Path(filename).is_absolute() or (len(filename) >= 2 and filename[1] == ":"):
        return f"filename 은 절대 경로가 될 수 없습니다: {filename!r}."

    return None


def _validate_kind_extension(filename: str, kind: str) -> str | None:
    """filename 확장자가 kind 와 일치하는지 확인한다.

    Returns:
        오류 메시지(있으면) 또는 None.
    """
    allowed = _KIND_EXTENSIONS.get(kind)
    if allowed is None:
        return f"지원하지 않는 kind 입니다: {kind!r}."

    lower = filename.lower()
    if not any(lower.endswith(ext) for ext in allowed):
        return (
            f"kind={kind!r} 와 filename 확장자가 일치하지 않습니다: {filename!r}. "
            f"허용 확장자: {', '.join(allowed)}. "
            f"filename 을 올바른 확장자로 바꿔서 다시 호출하세요."
        )

    return None


def _to_relative_path(absolute: Path) -> str:
    """디스크 절대경로를 'result/<session>/<ts>/<file>' 상대 경로로 변환한다.

    display_markdown 등 시각화 도구는 RESULT_DIR 기준 상대 경로를 입력으로 받는다.
    """
    try:
        rel = absolute.relative_to(RESULT_DIR)
    except ValueError:
        # RESULT_DIR 밖에 저장된 비정상 경로 — 절대 경로 그대로 노출하지 않고
        # 파일명만 회신한다.
        logger.warning("save_artifact: target %s is outside RESULT_DIR", absolute)
        return absolute.name
    return _RESULT_PREFIX + str(rel).replace("\\", "/")


# ---------------------------------------------------------------------------
# 도구 등록
# ---------------------------------------------------------------------------


@register_tool(
    description=(
        "마크다운/JSON/텍스트 산출물을 result/<session>/<ts>/<filename> 경로에 저장한다. "
        "When to use: LLM 이 작성한 보고서·분석 데이터·구조화 결과를 사용자에게 영속적으로 "
        "남기고 싶을 때 호출. 단순 답변/요약은 텍스트로 충분하다. "
        "When NOT to use: 임시 계산 결과, 한 줄 응답, 또는 사용자가 명시적으로 저장을 "
        "원하지 않을 때. "
        "Expected chaining: 통상 save_artifact(kind='markdown') → display_markdown(source=반환path) "
        "또는 save_artifact(kind='json') → display_chart 순서로 사용한다. "
        "filename 은 슬래시·역슬래시·'..' 없는 단순 파일명만 허용하며, "
        "kind 와 확장자가 일치해야 한다 (markdown↔.md, json↔.json, text↔.txt)."
    ),
    slot_prompts={
        "filename": "산출물 파일명을 알려 주세요 (예: report.md).",
        "content": "저장할 본문 내용을 주세요.",
    },
    timeout_seconds=10,
)
async def save_artifact(
    filename: Annotated[
        str,
        "저장할 파일명 (확장자 포함, 경로 구분자 금지). 예: 'report.md', 'data.json'.",
    ],
    content: Annotated[
        str, "저장할 본문 텍스트. kind=json 일 때는 유효한 JSON 문자열."
    ],
    kind: Annotated[
        Literal["markdown", "json", "text"],
        "산출물 종류 — markdown(.md), json(.json), text(.txt)",
    ] = "markdown",
) -> ToolResult:
    """LLM 산출물을 현재 세션의 타임스탬프 슬롯에 저장한다.

    같은 턴 내 다회 호출하면 ``turn_slot()`` 캐시 덕분에 동일 폴더에 모인다.
    저장에 성공하면 display_markdown 등 후속 도구가 그대로 받아들일 수 있는
    'result/...' 상대 경로를 ``ToolResult.data['path']`` 로 반환한다.

    Args:
        filename: 저장 파일명 (단순 파일명).
        content: 저장 본문 텍스트.
        kind: 산출물 종류 (markdown/json/text).

    Returns:
        성공: ``ToolResult(content=요약, data={kind, path, size})``
        실패: ``ToolResult(is_error=True, content=원인 + 재시도 유도)``
    """
    filename_error = _validate_filename(filename)
    if filename_error:
        return ToolResult(
            content=f"[save_artifact 오류] {filename_error}",
            is_error=True,
        )

    extension_error = _validate_kind_extension(filename, kind)
    if extension_error:
        return ToolResult(
            content=f"[save_artifact 오류] {extension_error}",
            is_error=True,
        )

    if kind == "json":
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            return ToolResult(
                content=(
                    f"[save_artifact 오류] kind='json' 이지만 content 가 유효한 JSON 이 아닙니다: "
                    f"{exc.msg} (line {exc.lineno}, col {exc.colno}). "
                    "JSON 형식을 수정해 다시 호출하세요."
                ),
                is_error=True,
            )

    slot = turn_slot()
    target = slot / filename
    encoded = content.encode("utf-8")
    target.write_bytes(encoded)

    rel_path = _to_relative_path(target)
    logger.info("save_artifact wrote %d bytes -> %s", len(encoded), target)

    next_step_hint = (
        f"다음 단계로 display_markdown(source='{rel_path}') 호출 가능."
        if kind == "markdown"
        else ""
    )
    summary = f"저장 완료: {rel_path}"
    if next_step_hint:
        summary = f"{summary}\n{next_step_hint}"

    return ToolResult(
        content=summary,
        data={
            "kind": kind,
            "path": rel_path,
            "size": len(encoded),
            "filename": filename,
        },
    )
