"""open_curation 도구 — 큐레이션 확장 툴(evaluator 등)을 우측 패널에서 연다.

에이전트가 후보 parquet 들을 만든 뒤 이 도구를 한 번 호출하면:

1. 소스 parquet 경로들을 검증하고,
2. 번들 스펙(``<tool>.bundle.json``)을 현재 턴 슬롯에 쓰고,
3. ``data.kind="extension"`` 칩을 반환해 **우측 아티팩트 패널에 확장 SPA 를
   iframe 으로 임베드**한다. iframe 은 ``/ext/<tool>/?bundle=<rel>`` 을 열고, 확장
   툴이 번들의 parquet 들을 로드한다.

예전에는 마크다운 카드(``<tool>.curation.md``)를 띄워 사용자가 링크를 새 탭으로
열게 했지만, 데스크탑 앱에서 새 탭은 맥락을 끊으므로 **패널 내 iframe 임베드**로
바꿨다. 패널 헤더의 '새 탭' 버튼으로 별도 창에서도 열 수 있다(프론트
``ArtifactExtension`` 컴포넌트).

이 도구는 **evaluator 에 특정되지 않는다** — ``tool`` 인자로 어떤 확장 툴이든 가리킬
수 있고, ``mapping`` 도 해석하지 않고 번들에 그대로 실어 보낸다(확장 툴이 해석).
확장 시스템의 진입 규약을 한 곳에 모은 제네릭 호스트 훅이다.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from agent.models import ToolResult
from agent.registries.tools import register_tool
from core.result_store import resolve_result_path, to_result_relative, turn_slot

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

# 확장 툴 이름 — /ext/<tool>/ 경로 세그먼트로 쓰이므로 안전한 문자만 허용한다.
_TOOL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
# 정적 SPA 마운트 prefix (core.extensions_loader._STATIC_MOUNT_PREFIX 와 일치).
_EXT_MOUNT_PREFIX = "/ext"
# 번들 스펙 파일 명명 규약 (소스와 같은 턴 슬롯에 형제로 쓴다).
_BUNDLE_SUFFIX = ".bundle.json"


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _validate_sources(sources: list[str]) -> tuple[list[str], str | None]:
    """소스 경로들을 검증해 'result/...' 상대 경로 목록으로 환원한다.

    각 경로는 ``resolve_result_path`` 로 containment·존재 여부를 확인하고 parquet
    확장자인지 검사한다.

    Args:
        sources: 검토할 parquet 경로 목록 (각 'result/...' 형식).

    Returns:
        (검증된 'result/...' 경로 목록, None) 성공
        ([], 오류 메시지) 실패 — 첫 번째로 실패한 경로의 사유.
    """
    if not sources:
        return [], (
            "sources 가 비어 있습니다. 검토할 parquet 경로를 1개 이상 전달하세요."
        )

    resolved: list[str] = []
    for src in sources:
        target, error = resolve_result_path(src)
        if error or target is None:
            return [], f"소스 경로 해석 실패: {error}"
        if target.suffix.lower() != ".parquet":
            return [], f"parquet 산출물만 큐레이션할 수 있습니다: {src!r}"
        resolved.append(to_result_relative(target))
    return resolved, None


def _is_valid_mapping_value(value: object) -> bool:
    """매핑 값이 허용 형식인지 검사한다 — 문자열 또는 문자열 리스트.

    레전드 등 일부 역할은 다중 컬럼(list[str])을 받을 수 있으므로(확장 툴이 합성해
    해석), str 뿐 아니라 list[str] 도 허용한다.
    """
    if isinstance(value, str):
        return True
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _validate_mapping(
    mapping: dict[str, str | list[str]] | None,
) -> tuple[dict[str, str | list[str]], str | None]:
    """컬럼 역할 매핑을 검증한다 (선택 인자).

    역할 키의 의미는 확장 툴이 해석하므로 여기서 키 집합을 강제하지 않는다 — 평탄한
    ``{문자열: 문자열|문자열리스트}`` 딕셔너리인지만 확인한다. 리스트 값은 다중 컬럼
    역할(예: legend 다중 합성)을 위해 허용한다.

    Args:
        mapping: ``{역할: 컬럼명}`` 또는 ``{역할: [컬럼명, ...]}`` 딕셔너리, 또는 None.

    Returns:
        (검증된 매핑(없으면 빈 dict), None) 성공 / ({}, 오류 메시지) 실패.
    """
    if mapping is None:
        return {}, None
    if not isinstance(mapping, dict) or not all(
        isinstance(k, str) and _is_valid_mapping_value(v) for k, v in mapping.items()
    ):
        return {}, (
            "mapping 은 {역할: 컬럼명} 형식의 딕셔너리여야 합니다 "
            "(값은 문자열 또는 문자열 리스트; 예: "
            '{"select": "item_id", "legend": ["category", "region"]}).'
        )
    return mapping, None


def _write_text(target: Path, text: str) -> str | None:
    """텍스트 파일을 쓰고, 실패 시 오류 메시지를 반환한다 (성공 시 None)."""
    try:
        target.write_text(text, encoding="utf-8")
    except OSError as exc:
        return str(exc)
    return None


# ---------------------------------------------------------------------------
# 도구 등록
# ---------------------------------------------------------------------------


@register_tool(
    description=(
        "후보 데이터(parquet)를 사람이 검토·선별하는 큐레이션 확장 도구를 "
        "채팅창 우측 패널에 iframe 으로 연다. "
        "When to use: 분석으로 만든 후보 parquet 들을 사용자가 시각적으로 검토·선별해야 할 때 "
        "(SKILL 의 마지막 핸드오프 단계). 후보를 모두 만든 뒤 **마지막에 한 번만** 호출한다. "
        "When NOT to use: 데이터를 그냥 보여줄 때(display_chart/display_markdown), "
        "또는 parquet 이 아직 저장되지 않았을 때(save_artifact 로 먼저 저장). "
        "Expected chaining: save_artifact(kind='parquet', ...) × N → "
        "open_curation(tool='evaluator', sources=[저장된 경로들], mapping={...}). "
        "tool 은 확장 툴 이름(예: 'evaluator') — /ext/<tool>/ 로 열린다. "
        "sources 는 검토할 parquet 의 'result/...' 경로 리스트(1개 이상). "
        "mapping 은 컬럼 역할→컬럼명 딕셔너리로, 확장 툴이 해석한다(생략 시 툴 기본값). "
        "evaluator 의 역할 키: select(리스트 항목 키)·sort(정수 순위)·x·y(scatter 축)·"
        "legend(시리즈 그룹)·desc(보조 설명). "
        "mark 는 기본 차트 종류(선택) — evaluator 는 "
        "scatter/line/bar/box/histogram/ecdf/heatmap 을 받으며 생략 시 scatter. "
        "이 도구는 확장 칩 1개를 우측 패널에 표시하고 확장 도구를 바로 연다 "
        "(패널 헤더의 '새 탭' 버튼으로 별도 창에서도 열 수 있다)."
    ),
    slot_prompts={
        "tool": "어떤 큐레이션 확장 도구를 열까요? (예: 'evaluator')",
        "sources": "검토할 parquet 경로 리스트를 알려 주세요 (예: ['result/<session>/<ts>/candidates.parquet']).",
    },
    timeout_seconds=10,
)
async def open_curation(
    tool: Annotated[
        str,
        "큐레이션 확장 툴 이름 (영소문자/숫자/_/-). /ext/<tool>/ 경로로 열린다. 예: 'evaluator'.",
    ],
    sources: Annotated[
        list[str],
        "검토할 parquet 의 'result/...' 경로 리스트 (1개 이상). save_artifact 가 반환한 경로를 그대로 전달.",
    ],
    mapping: Annotated[
        dict[str, str | list[str]] | None,
        "컬럼 역할→컬럼명 딕셔너리 (확장 툴이 해석). 생략 시 툴 기본값. 값은 문자열 "
        "또는 문자열 리스트(다중 컬럼 역할, 예: legend 다중 합성). "
        '예: {"select": "item_id", "sort": "rank", "x": "tkout_time", "y": "value", '
        '"legend": ["category", "region"], "desc": "item_desc"}.',
    ] = None,
    mark: Annotated[
        str,
        "기본 차트 종류 (확장 툴이 해석, 생략 가능). evaluator 는 "
        "scatter/line/bar/box/histogram/ecdf/heatmap 중 하나. 사용자가 도구 안에서 바꿀 수 있다.",
    ] = "",
    title: Annotated[str, "카드 제목 (패널 헤더·탭에 표시)"] = "",
) -> ToolResult:
    """큐레이션 확장 도구를 우측 패널에 iframe 으로 연다.

    소스 경로를 검증하고, 번들 스펙을 현재 턴 슬롯에 쓴 뒤, ``data.kind="extension"``
    칩을 반환해 패널이 ``/ext/<tool>/?bundle=...`` 을 iframe 으로 임베드하게 한다.

    Args:
        tool: 확장 툴 이름 (/ext/<tool>/ 세그먼트).
        sources: 검토할 parquet 의 'result/...' 경로 목록.
        mapping: 컬럼 역할 매핑 (선택, 확장 툴이 해석).
        mark: 기본 차트 종류 (선택, 확장 툴이 해석 — 비면 번들에서 생략).
        title: 카드 제목 (선택).

    Returns:
        성공: ``ToolResult(content=요약, data={kind:"extension", tool, src, title, bundle})``
        실패: ``ToolResult(is_error=True, content=원인 + 재시도 유도)``
    """
    tool_name = (tool or "").strip()
    if not _TOOL_NAME_RE.match(tool_name):
        return ToolResult(
            content=(
                f"[open_curation 오류] tool 이름은 영소문자/숫자/_/- 만 허용합니다: {tool!r}."
            ),
            is_error=True,
        )

    resolved_sources, source_error = _validate_sources(sources)
    if source_error:
        return ToolResult(content=f"[open_curation 오류] {source_error}", is_error=True)

    clean_mapping, mapping_error = _validate_mapping(mapping)
    if mapping_error:
        return ToolResult(
            content=f"[open_curation 오류] {mapping_error}", is_error=True
        )

    slot = turn_slot()

    bundle = {"tool": tool_name, "sources": resolved_sources, "mapping": clean_mapping}
    # mark 는 제네릭 통과값 — 호스트는 해석하지 않고 번들에 그대로 실어 확장이 처리한다.
    mark_name = (mark or "").strip()
    if mark_name:
        bundle["mark"] = mark_name
    bundle_path = slot / f"{tool_name}{_BUNDLE_SUFFIX}"
    write_error = _write_text(
        bundle_path, json.dumps(bundle, ensure_ascii=False, indent=2)
    )
    if write_error:
        return ToolResult(
            content=f"[open_curation 오류] 번들 저장 실패: {write_error}",
            is_error=True,
        )

    bundle_rel = to_result_relative(bundle_path)
    src = f"{_EXT_MOUNT_PREFIX}/{tool_name}/?bundle={quote(bundle_rel, safe='')}"
    label = title or f"큐레이션: {tool_name}"
    logger.info(
        "open_curation: tool=%s sources=%d bundle=%s",
        tool_name,
        len(resolved_sources),
        bundle_rel,
    )

    return ToolResult(
        content=(
            f"큐레이션 도구를 우측 패널에 열었습니다 (도구: {tool_name}, 소스 "
            f"{len(resolved_sources)}개). 사용자가 패널에서 직접 검토·선별합니다."
        ),
        data={
            "kind": "extension",
            "tool": tool_name,
            "src": src,
            "title": label,
            "bundle": bundle_rel,
        },
    )
