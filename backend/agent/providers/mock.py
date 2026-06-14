"""Mock LLM provider — 실제 LLM 없이 Harness/UI 전체 파이프라인을 결정론적으로 검증한다.

5개 시나리오가 사용자 입력 트리거에 따라 분기 실행된다. Mock 은 ToolCallEvent /
DeltaEvent / ReasoningEvent / DoneEvent 만 yield 하며, 도구 실행·결과 합성·TodoUpdate /
AgentSwitch / AgentReturn / SkillActive / SkillComplete / ToolResult 등 UI 이벤트는
모두 Harness 가 자동으로 처리한다.

============================================================
시나리오 카탈로그
============================================================
    A. echo (fallback)               (그 외 모든 입력)
        검증: DeltaEvent 스트리밍 — 기본 markdown 렌더링

    B. reasoning + ask_user          trigger="추천해줘", "골라줘", "help me decide"
        검증: ReasoningBlock · AskUserCard(input_type=both) · 답변 후속 echo

    C. time_check SKILL (standalone) trigger="지금 시간", "현재 시각", "몇 시야"
        검증: SkillBadge(time_check) · now → save_artifact +
              display_markdown → 자연어 응답 (Artifact 패널 markdown 탭)

    D. data_summary via analyst_agent (Case 3 단일 위임)
                                     trigger="데이터 요약", "요약 통계"
        검증: SkillBadge(data_summary) · AgentSwitch/Return · AgentProgress 래핑
              · sub 안 ReasoningBlock / TodoProgress(3) / SkillCompleteBadge
              · exec_code + call_function + eval_expression 3종 메타 도구
              · display_chart(6 차트: bar/line/scatter/box + 그룹 scatter/ecdf)
                — 마지막 2개는 color 채널로 레전드 컨트롤 검증 · 오케스트레이터 최종 보고

    E. composite — analyst → writer  trigger="전체 분석 보고서", "종합 보고서"
        검증: 오케스트레이터 multi-step plan(2) · AgentTrail 칩 2개
              · analyst sub: exec_code + call_function + display_chart + TodoProgress(2)
              · writer sub: save_artifact + display_markdown
              · 최종 ReasoningEvent + markdown 통합 보고

    F. parallel — analyst ∥ writer    trigger="병렬 분석", "동시 분석", "parallel"
        검증: 오케스트레이터가 call_sub_agents_parallel 로 독립 두 작업을 동시 위임
              · 두 AgentTrail(analyst·writer)이 인터리브되어 동시 진행·완료
              · dispatch_id 라우팅 · 단일 통합 tool_result → 최종 통합 보고
              (sub 흐름은 D analyst·E writer 를 재사용 — composite marker 없음)

    G. artifact 재사용                trigger="이전 결과", "지난 분석", "예전 데이터"
        검증: list_artifacts(재발견) → load_artifact(parquet → namespace) →
              exec_code(재계산) 의 읽기 방향 체인. 보통 D 를 먼저 실행해
              산출물이 디스크에 있는 상태를 전제한다.

============================================================
상태 추적 패턴
============================================================
각 시나리오 단계는 `tool_call_id` prefix 로 식별된다. _has_recent_tool_result(prefix)
가 직전 턴의 도구 결과를 검사해 다음 단계로 진입할지 결정한다. add_todo 의 task_id
는 _extract_task_ids 로 결과 텍스트에서 정규식 추출한다.

Sub-agent context 는 system 메시지의 "당신은 '" marker 로 판별한다 (Harness 의
_compose_sub_agent_system_prompt 가 항상 주입). 같은 analyst_agent 라도 task 텍스트에
[E-composite] marker 가 있으면 E 분기로, 없으면 D 분기로 라우팅된다.
"""

import asyncio
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator
from typing import Any

from agent.models import (
    DeltaEvent,
    DoneEvent,
    Message,
    ReasoningEvent,
    StreamEvent,
    ToolCall,
    ToolCallEvent,
    ToolSpec,
)
from agent.registries.tools import ASK_USER
from core.result_store import artifact_slot, session_dir_name

logger = logging.getLogger(__name__)

# 스트리밍 체감을 위한 토큰 간 지연 (초).
_MOCK_TOKEN_DELAY = 0.02

# ============================================================
# 트리거 상수
# ============================================================
_B_TRIGGERS = ("추천해줘", "골라줘", "help me decide")
_C_TRIGGERS = ("지금 시간", "현재 시각", "몇 시야", "몇 시인가요", "what time")
_D_TRIGGERS = ("데이터 요약", "요약 통계", "summary stats", "통계 계산")
_E_TRIGGERS = ("전체 분석 보고서", "종합 보고서", "종합 분석 보고서")
_F_TRIGGERS = ("병렬 분석", "동시 분석", "parallel")
_G_TRIGGERS = ("이전 결과", "지난 분석", "예전 데이터", "아까 저장", "reuse artifact")
_H_TRIGGERS = ("순위 검토", "후보 큐레이션", "검토 큐레이션", "큐레이션 도구")

# ============================================================
# Marker — sub-agent context 및 composite 분기 판별
# ============================================================
# Harness 의 _compose_sub_agent_system_prompt 가 항상 포함하는 헤더.
_SUB_AGENT_MARKER = "당신은 '"

# 오케스트레이터가 E 시나리오에서 sub-agent 에게 위임할 때 task 에 박는 marker.
# sub-agent context 의 Mock 이 이 marker 로 D(단일) vs E(복합) 를 결정론적으로 구분.
_COMPOSITE_TASK_MARKER = "[E-composite]"


class MockProvider:
    """LLM 없이 Harness/UI 전체 파이프라인을 검증하기 위한 결정론 가짜 프로바이더.

    분기 우선순위 (위에서부터 검사):
        1) sub-agent context (system marker 로 판별)
            - analyst_agent + [E-composite] marker → E analyst sub
            - writer_agent  + [E-composite] marker → E writer sub
            - analyst_agent (marker 없음)        → D analyst sub
            - 그 외 sub-agent (현재 미사용)        → 간단한 complete_subagent 종료
        2a) 오케스트레이터 — F parallel (트리거 매칭 또는 진행 중 상태)
        2) 오케스트레이터 — E composite (트리거 매칭 또는 진행 중 상태)
        3) 오케스트레이터 — D single (트리거 매칭 또는 진행 중 상태)
        4) C time_check SKILL 흐름 (트리거 매칭 또는 진행 중 상태)
        5) B reasoning + ask_user (트리거 매칭 또는 답변 후속)
        6) A echo (기본 fallback)
    """

    async def astream(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> AsyncIterator[StreamEvent]:
        del tools  # mock 은 도구 스펙을 참조하지 않음

        # ───────────────────────────────────────────────────────────────
        # 1) Sub-agent context 우선 처리
        # ───────────────────────────────────────────────────────────────
        sub_name = _detect_sub_agent_name(messages)
        if sub_name is not None:
            async for event in _route_sub_agent(messages, sub_name):
                yield event
            return

        last_user = _find_last_user(messages)

        # ───────────────────────────────────────────────────────────────
        # 2a) F parallel — 진행 중이거나 새 트리거 (E 보다 먼저 검사)
        # ───────────────────────────────────────────────────────────────
        if _is_F_active(messages, last_user):
            async for event in _scenario_F_orchestrator(messages):
                yield event
            return

        # ───────────────────────────────────────────────────────────────
        # 2) E composite — 진행 중이거나 새 트리거
        # ───────────────────────────────────────────────────────────────
        if _is_E_active(messages, last_user):
            async for event in _scenario_E_orchestrator(messages):
                yield event
            return

        # ───────────────────────────────────────────────────────────────
        # 3) D single — 진행 중이거나 새 트리거
        # ───────────────────────────────────────────────────────────────
        if _is_D_active(messages, last_user):
            async for event in _scenario_D_orchestrator(messages):
                yield event
            return

        # ───────────────────────────────────────────────────────────────
        # 3b) G artifact 재사용 — 과거 산출물 재발견·재로드 (D 이후 후속 턴)
        # ───────────────────────────────────────────────────────────────
        if _is_G_active(messages, last_user):
            async for event in _scenario_G_artifact_reuse(messages):
                yield event
            return

        # ───────────────────────────────────────────────────────────────
        # 3c) H 큐레이션 핸드오프 — 후보 parquet → open_curation 진입 카드
        # ───────────────────────────────────────────────────────────────
        if _is_H_active(messages, last_user):
            async for event in _scenario_H_curation(messages):
                yield event
            return

        # ───────────────────────────────────────────────────────────────
        # 4) C time_check — 진행 중이거나 새 트리거
        # ───────────────────────────────────────────────────────────────
        if _is_C_active(messages, last_user):
            async for event in _scenario_C_time_check(messages):
                yield event
            return

        # ───────────────────────────────────────────────────────────────
        # 5) B reasoning + ask_user
        # ───────────────────────────────────────────────────────────────
        if _has_recent_tool_result(messages, "mock-B-ask-"):
            # 사용자가 ask_user 에 답변 후 다음 턴 — echo 응답.
            async for event in _scenario_B_after_answer(last_user):
                yield event
            return

        if last_user is not None and _matches(last_user.content, _B_TRIGGERS):
            async for event in _scenario_B_ask_user(last_user.content):
                yield event
            return

        # ───────────────────────────────────────────────────────────────
        # 6) A echo (fallback)
        # ───────────────────────────────────────────────────────────────
        reply = _compose_reply(last_user)
        for ch in reply:
            await asyncio.sleep(_MOCK_TOKEN_DELAY)
            yield DeltaEvent(content=ch)
        yield DoneEvent()


# =============================================================================
# Sub-agent 라우터
# =============================================================================


async def _route_sub_agent(
    messages: list[Message], agent_name: str
) -> AsyncIterator[StreamEvent]:
    """sub-agent context 에서 agent_name + task marker 로 분기한다."""
    task_text = _find_sub_task_text(messages)
    is_composite = task_text is not None and _COMPOSITE_TASK_MARKER in task_text

    if agent_name == "analyst_agent":
        if is_composite:
            async for ev in _scenario_E_analyst_sub(messages):
                yield ev
        else:
            async for ev in _scenario_D_analyst_sub(messages):
                yield ev
        return

    if agent_name == "writer_agent":
        async for ev in _scenario_E_writer_sub(messages):
            yield ev
        return

    # 미정의 sub-agent — 안전한 종료만 yield.
    yield ToolCallEvent(
        call=ToolCall(
            id=f"mock-sub-unknown-finish-{uuid.uuid4().hex[:8]}",
            name="complete_subagent",
            arguments={"summary": f"{agent_name} — mock 미정의 에이전트, 즉시 종료."},
        )
    )
    yield DoneEvent()


# =============================================================================
# Scenario B — reasoning + ask_user
# =============================================================================


async def _scenario_B_ask_user(user_text: str) -> AsyncIterator[StreamEvent]:
    """ReasoningEvent 청크 → ask_user(both 모드) 호출 → Done."""
    reasoning = (
        f"사용자가 '{user_text}' 라고 했습니다. "
        "선호를 파악하기 위해 객관식과 자유 입력을 함께 제공하는 ask_user 를 호출합니다..."
    )
    for i in range(0, len(reasoning), 5):
        await asyncio.sleep(_MOCK_TOKEN_DELAY)
        yield ReasoningEvent(content=reasoning[i : i + 5])

    yield ToolCallEvent(
        call=ToolCall(
            id=f"mock-B-ask-{uuid.uuid4().hex[:8]}",
            name=ASK_USER,
            arguments={
                "question": "어떤 옵션이 가장 마음에 드시나요?",
                "options": [
                    "옵션 A — 빠른 실행",
                    "옵션 B — 균형형",
                    "옵션 C — 안정성 우선",
                ],
                "input_type": "both",
            },
        )
    )
    yield DoneEvent()


async def _scenario_B_after_answer(
    last_user: Message | None,
) -> AsyncIterator[StreamEvent]:
    """사용자 답변을 받은 다음 턴 — 선택을 확인하고 마무리한다."""
    answer = last_user.content if last_user is not None else "(빈 답변)"
    reply = (
        f"'{answer}' 으로 선택을 확정했습니다. "
        "실제 LLM 환경에서는 이 입력을 바탕으로 후속 작업을 자동 진행합니다."
    )
    for ch in reply:
        await asyncio.sleep(_MOCK_TOKEN_DELAY)
        yield DeltaEvent(content=ch)
    yield DoneEvent()


# =============================================================================
# Scenario C — time_check SKILL (standalone)
# =============================================================================

_C_NOW_PREFIX = "mock-C-now-"
_C_SAVE_PREFIX = "mock-C-save-"
_C_MD_PREFIX = "mock-C-md-"


def _is_C_active(messages: list[Message], last_user: Message | None) -> bool:
    """C 흐름이 진행 중이거나 새 트리거가 들어왔는지 판별."""
    if _has_recent_tool_result(messages, _C_NOW_PREFIX):
        return True
    return last_user is not None and _matches(last_user.content, _C_TRIGGERS)


async def _scenario_C_time_check(
    messages: list[Message],
) -> AsyncIterator[StreamEvent]:
    """3 턴 흐름: now → save_artifact+display_markdown → 자연어 응답."""
    has_now = _has_recent_tool_result(messages, _C_NOW_PREFIX)
    has_md = _has_recent_tool_result(messages, _C_MD_PREFIX)

    # 턴 1: now 호출.
    if not has_now:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_C_NOW_PREFIX}{uuid.uuid4().hex[:8]}",
                name="now",
                arguments={},
            )
        )
        yield DoneEvent()
        return

    # 턴 2: save_artifact + display_markdown 동시.
    if not has_md:
        now_text = _latest_tool_content(messages, _C_NOW_PREFIX) or "(시각 정보 없음)"
        log_content = (
            "# 현재 시각 기록\n\n"
            f"- 조회 시각 (ISO 8601): `{now_text}`\n"
            "- 조회 출처: `now()` 빌트인 도구\n"
            "- 작업 단계: time_check SKILL 의 표준 절차에 따라 자동 저장\n"
        )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_C_SAVE_PREFIX}{uuid.uuid4().hex[:8]}",
                name="save_artifact",
                arguments={
                    "filename": "time_log.md",
                    "content": log_content,
                    "kind": "markdown",
                },
            )
        )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_C_MD_PREFIX}{uuid.uuid4().hex[:8]}",
                name="display_markdown",
                arguments={
                    "source": f"result/{session_dir_name()}/{_current_turn_slot_name()}/time_log.md",
                    "title": "현재 시각 기록",
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 3: 자연어 최종 응답.
    now_text = _latest_tool_content(messages, _C_NOW_PREFIX) or "(알 수 없음)"
    reply = (
        f"현재 시각은 **{now_text}** 입니다.\n\n"
        "우측 패널에 시각 기록(마크다운) 산출물이 표시되었습니다."
    )
    for ch in reply:
        await asyncio.sleep(_MOCK_TOKEN_DELAY)
        yield DeltaEvent(content=ch)
    yield DoneEvent()


def _current_turn_slot_name() -> str:
    """현재 턴 슬롯의 폴더명(YYYYMMDD-HHmmss). save_artifact 가 사용할 폴더와 일치."""
    slot = artifact_slot()
    return slot.name


# =============================================================================
# Scenario G — artifact 재발견·재사용 (list_artifacts → load_artifact → exec_code)
# =============================================================================

_G_LIST_PREFIX = "mock-G-list-"
_G_LOAD_PREFIX = "mock-G-load-"
_G_EXEC_PREFIX = "mock-G-exec-"


def _is_G_active(messages: list[Message], last_user: Message | None) -> bool:
    """G 흐름이 진행 중이거나 새 트리거가 들어왔는지 판별."""
    if _has_recent_tool_result(messages, _G_LIST_PREFIX):
        return True
    return last_user is not None and _matches(last_user.content, _G_TRIGGERS)


def _extract_first_parquet_path(
    messages: list[Message], list_prefix: str
) -> str | None:
    """list_artifacts 결과 텍스트에서 첫 'result/...parquet' 경로를 추출한다."""
    content = _latest_tool_content(messages, list_prefix)
    if not content:
        return None
    # 세션 폴더명에 공백이 포함될 수 있어(예: '데이터 요약-...') \S+ 대신 비-개행 매칭.
    # 비탐욕(+?)으로 줄 내 첫 '.parquet' 까지만 잡는다.
    match = re.search(r"(result/[^\n]+?\.parquet)", content)
    return match.group(1) if match else None


async def _scenario_G_artifact_reuse(
    messages: list[Message],
) -> AsyncIterator[StreamEvent]:
    """과거 산출물 재사용 흐름 — 디스크의 parquet 를 재발견해 namespace 로 되살린다.

    실제 LLM 이 '아까 그 데이터로 다시 분석해줘' 류 요청을 받았을 때의 표준 경로를
    모사한다: list_artifacts 로 경로 발견 → load_artifact 로 namespace 로드 →
    exec_code 로 재계산. 보통 시나리오 D 를 먼저 실행해 산출물이 있는 상태를 전제한다.
    """
    has_list = _has_recent_tool_result(messages, _G_LIST_PREFIX)
    has_load = _has_recent_tool_result(messages, _G_LOAD_PREFIX)
    has_exec = _has_recent_tool_result(messages, _G_EXEC_PREFIX)

    # 턴 1: list_artifacts 로 현재 세션 산출물 조회.
    if not has_list:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_G_LIST_PREFIX}{uuid.uuid4().hex[:8]}",
                name="list_artifacts",
                arguments={"kind": "parquet"},
            )
        )
        yield DoneEvent()
        return

    parquet_path = _extract_first_parquet_path(messages, _G_LIST_PREFIX)

    # 재사용할 parquet 가 없으면 — 사용자에게 먼저 분석을 돌리라고 안내.
    if parquet_path is None:
        reply = (
            "현재 세션에 재사용할 parquet 산출물이 없습니다. "
            "먼저 '데이터 요약' 으로 분석을 실행해 산출물을 만든 뒤 다시 시도해 주세요."
        )
        for ch in reply:
            await asyncio.sleep(_MOCK_TOKEN_DELAY)
            yield DeltaEvent(content=ch)
        yield DoneEvent()
        return

    # 턴 2: load_artifact 로 parquet 를 namespace 변수로 복원.
    if not has_load:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_G_LOAD_PREFIX}{uuid.uuid4().hex[:8]}",
                name="load_artifact",
                arguments={"path": parquet_path, "store_as": "reloaded_df"},
            )
        )
        yield DoneEvent()
        return

    # 턴 3: exec_code 로 재로드한 DataFrame 을 재계산.
    if not has_exec:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_G_EXEC_PREFIX}{uuid.uuid4().hex[:8]}",
                name="exec_code",
                arguments={
                    "code": (
                        "rows, cols = reloaded_df.shape\n"
                        "col_names = ', '.join(reloaded_df.columns)\n"
                        "print(f'재로드 완료: {rows} rows x {cols} cols ({col_names})')"
                    )
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 4: 자연어 최종 응답.
    exec_text = _latest_tool_content(messages, _G_EXEC_PREFIX) or "(재계산 결과 없음)"
    reply = (
        f"과거 산출물 `{parquet_path}` 를 다시 불러와 분석을 이어갈 준비를 마쳤습니다.\n\n"
        f"```\n{exec_text.strip()}\n```\n\n"
        "이제 `reloaded_df` 변수로 추가 전처리·시각화를 진행할 수 있습니다."
    )
    for ch in reply:
        await asyncio.sleep(_MOCK_TOKEN_DELAY)
        yield DeltaEvent(content=ch)
    yield DoneEvent()


# =============================================================================
# Scenario H — 큐레이션 핸드오프 (rank_review SKILL → open_curation)
# =============================================================================
# 오케스트레이터 직접 실행 (sub-agent 없음). 후보 parquet 를 만든 뒤 open_curation
# 으로 evaluator 진입 카드를 띄운다 — markdown 칩 재사용 + 새 탭 ?bundle= 링크 검증.

_H_EXEC_PREFIX = "mock-H-exec-"
_H_PARQUET_PREFIX = "mock-H-parquet-"
_H_OPEN_PREFIX = "mock-H-open-"

# rank_review SKILL 의 매핑 계약과 동일 (evaluator 역할 키 → 후보 컬럼명).
_H_MAPPING = {
    "select": "item_id",
    "sort": "rank",
    "x": "tkout_time",
    "y": "value",
    "legend": "category",
    "desc": "item_desc",
}


def _is_H_active(messages: list[Message], last_user: Message | None) -> bool:
    """H 흐름이 진행 중이거나 새 트리거가 들어왔는지 판별."""
    if _has_recent_tool_result(messages, _H_EXEC_PREFIX):
        return True
    return last_user is not None and _matches(last_user.content, _H_TRIGGERS)


def _build_candidates_df_code() -> str:
    """exec_code 에 전달할 후보 DataFrame(cand_df) 생성 코드.

    evaluator 예시 스키마(item_id·item_desc·rank·tkout_time·category·value)를 따른다.
    품목 4개를 POR/NEW × 3개 시각으로 펼쳐 scatter 레전드(category) 데모를 만든다.
    """
    return (
        "import polars as pl\n"
        "from datetime import datetime\n"
        "_items = [('A', '품목 A', 1), ('B', '품목 B', 2), "
        "('C', '품목 C', 3), ('D', '품목 D', 4)]\n"
        "_rows = []\n"
        "for _id, _desc, _rank in _items:\n"
        "    for _cat in ('POR', 'NEW'):\n"
        "        for _hh in (9, 13, 18):\n"
        "            _base = 80 + _rank * 2 + (5 if _cat == 'NEW' else 0)\n"
        "            _rows.append({\n"
        "                'item_id': _id, 'item_desc': _desc, 'rank': _rank,\n"
        "                'tkout_time': datetime(2026, 6, 14, _hh, 0),\n"
        "                'category': _cat, 'value': _base + _hh,\n"
        "            })\n"
        "cand_df = pl.DataFrame(_rows)\n"
        "print(f'후보 생성: cand_df shape={cand_df.shape}')"
    )


async def _scenario_H_curation(
    messages: list[Message],
) -> AsyncIterator[StreamEvent]:
    """rank_review SKILL 핸드오프 흐름 — 후보 parquet 생성 → open_curation 카드.

    턴 1: exec_code(cand_df — evaluator 스키마)
    턴 2: save_artifact(parquet, candidates.parquet, source=$cand_df)
    턴 3: open_curation(tool='evaluator', sources=[저장경로], mapping=_H_MAPPING)
    턴 4: 자연어 최종 응답
    """
    has_exec = _has_recent_tool_result(messages, _H_EXEC_PREFIX)
    has_parquet = _has_recent_tool_result(messages, _H_PARQUET_PREFIX)
    has_open = _has_recent_tool_result(messages, _H_OPEN_PREFIX)

    # 턴 1: 후보 데이터 생성.
    if not has_exec:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_H_EXEC_PREFIX}{uuid.uuid4().hex[:8]}",
                name="exec_code",
                arguments={"code": _build_candidates_df_code()},
            )
        )
        yield DoneEvent()
        return

    # 턴 2: candidates.parquet 저장.
    if not has_parquet:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_H_PARQUET_PREFIX}{uuid.uuid4().hex[:8]}",
                name="save_artifact",
                arguments={
                    "filename": "candidates.parquet",
                    "kind": "parquet",
                    "source": "$cand_df",
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 3: open_curation — 저장된 parquet 경로를 tool_result 에서 파싱해 전달.
    if not has_open:
        parquet_path = _extract_artifact_path(messages, _H_PARQUET_PREFIX)
        if parquet_path is None:
            reply = (
                "후보 parquet 저장 결과를 확인하지 못해 큐레이션 카드를 만들 수 없습니다. "
                "다시 시도해 주세요."
            )
            for ch in reply:
                await asyncio.sleep(_MOCK_TOKEN_DELAY)
                yield DeltaEvent(content=ch)
            yield DoneEvent()
            return

        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_H_OPEN_PREFIX}{uuid.uuid4().hex[:8]}",
                name="open_curation",
                arguments={
                    "tool": "evaluator",
                    "sources": [parquet_path],
                    "mapping": _H_MAPPING,
                    "title": "순위 검토 큐레이션",
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 4: 자연어 최종 응답.
    reply = (
        "검토 후보 데이터를 준비하고 **큐레이션 진입 카드**를 우측 패널에 표시했습니다.\n\n"
        "카드의 **'🔍 큐레이션 도구 열기'** 링크를 클릭하면 새 탭에서 evaluator 가 열려 "
        "품목을 직접 검토·선별·내보내기 할 수 있습니다.\n\n"
        "> 소스 선정이 잘못됐다면 도구 안에서 후보를 더하거나 빼며 교정할 수 있습니다."
    )
    for ch in reply:
        await asyncio.sleep(_MOCK_TOKEN_DELAY)
        yield DeltaEvent(content=ch)
    yield DoneEvent()


# =============================================================================
# Scenario D — data_summary via analyst_agent (Case 3 단일 위임)
# =============================================================================

_D_DISPATCH_PREFIX = "mock-D-orch-dispatch-"


def _is_D_active(messages: list[Message], last_user: Message | None) -> bool:
    if _has_recent_tool_result(messages, _D_DISPATCH_PREFIX):
        return True
    return last_user is not None and _matches(last_user.content, _D_TRIGGERS)


async def _scenario_D_orchestrator(
    messages: list[Message],
) -> AsyncIterator[StreamEvent]:
    """오케스트레이터: 1턴=위임, 2턴=자연어 최종 보고."""
    has_dispatch = _has_recent_tool_result(messages, _D_DISPATCH_PREFIX)

    # 턴 1: analyst_agent 위임.
    if not has_dispatch:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_D_DISPATCH_PREFIX}{uuid.uuid4().hex[:8]}",
                name="call_sub_agent",
                arguments={
                    "agent_name": "analyst_agent",
                    "task": "요약 통계 계산 및 시각화 — 임의 표본 30개에 대해 평균·표준편차 등 6개 지표를 계산하고 막대 차트로 시연하라.",
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 2: sub-agent 반환 후 통합 보고.
    summary = _latest_tool_content(messages, _D_DISPATCH_PREFIX) or "(요약 없음)"
    reply = (
        "분석 에이전트의 작업이 완료되었습니다.\n\n"
        "**분석가 요약**\n"
        f"> {summary}\n\n"
        "우측 패널의 차트로 각 통계량을 직접 확인할 수 있습니다."
    )
    for ch in reply:
        await asyncio.sleep(_MOCK_TOKEN_DELAY)
        yield DeltaEvent(content=ch)
    yield DoneEvent()


# --- D analyst sub-agent flow -------------------------------------------------

_D_SUB_ADD_PREFIX = "mock-D-sub-add-"
_D_SUB_CALL_PREFIX = "mock-D-sub-call-"
_D_SUB_PARQUET_PREFIX = "mock-D-sub-parquet-"
_D_SUB_SPEC_PREFIX = "mock-D-sub-spec-"
_D_SUB_CHART_PREFIX = "mock-D-sub-chart-"
_D_SUB_COMPLETE_PREFIX = "mock-D-sub-complete-"
_D_SUB_FINISH_PREFIX = "mock-D-sub-finish-"


async def _scenario_D_analyst_sub(
    messages: list[Message],
) -> AsyncIterator[StreamEvent]:
    """analyst_agent sub-context (D 단일 위임) — 신규 parquet + spec 파이프라인.

    턴 1: ReasoningEvent + add_todo(3) → [샘플+통계, 데이터 직렬화, spec+표시]
    턴 2: exec_code(polars samples_df) + call_function(stats_df)
          + eval_expression(mean 추출) + complete_todo(1)
    턴 3: save_artifact(parquet, samples.parquet) + save_artifact(parquet, stats.parquet)
          + complete_todo(2)
    턴 4: save_artifact(json, charts.spec.json) + display_chart(spec 경로)
          + complete_todo(3)
    턴 5: complete_subagent
    """
    has_add = _has_recent_tool_result(messages, _D_SUB_ADD_PREFIX)
    has_call = _has_recent_tool_result(messages, _D_SUB_CALL_PREFIX)
    has_parquet = _has_recent_tool_result(messages, _D_SUB_PARQUET_PREFIX)
    has_chart = _has_recent_tool_result(messages, _D_SUB_CHART_PREFIX)
    task_ids = _extract_task_ids(messages, _D_SUB_ADD_PREFIX)
    completed = _count_completes(messages, _D_SUB_COMPLETE_PREFIX)

    # 턴 1: ReasoningEvent + add_todo(3).
    if not has_add:
        reasoning = (
            "데이터 요약 통계를 계산하기 위해 작업을 3단계로 분해합니다. "
            "polars DataFrame 생성 + 통계 계산 → parquet 직렬화 → 차트 spec 작성·표시 순서입니다..."
        )
        for i in range(0, len(reasoning), 6):
            await asyncio.sleep(_MOCK_TOKEN_DELAY)
            yield ReasoningEvent(content=reasoning[i : i + 6])

        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_D_SUB_ADD_PREFIX}{uuid.uuid4().hex[:8]}",
                name="add_todo",
                arguments={
                    "items": [
                        {
                            "description": "samples_df (30행) 생성 + 요약 통계 stats_df 산출"
                        },
                        {
                            "description": "samples.parquet · stats.parquet 디스크 직렬화"
                        },
                        {"description": "charts.spec.json 작성 후 display_chart 호출"},
                    ]
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 2: exec_code (samples_df) + call_function (stats_df) + eval_expression + complete_todo(1).
    if not has_call and task_ids:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"mock-D-sub-exec-{uuid.uuid4().hex[:8]}",
                name="exec_code",
                arguments={"code": _build_samples_df_code(n=30, x_step=0.5, noise=0.4)},
            )
        )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_D_SUB_CALL_PREFIX}{uuid.uuid4().hex[:8]}",
                name="call_function",
                arguments={
                    "qualified_name": "scripts.stats_df.compute_summary_stats_df",
                    "kwargs": {"data": "$value_list"},
                    "store_as": "stats_df",
                },
            )
        )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"mock-D-sub-eval-{uuid.uuid4().hex[:8]}",
                name="eval_expression",
                arguments={
                    "expression": "stats_df.filter(stats_df['metric'] == 'mean')['value'][0]",
                    "store_as": "avg",
                },
            )
        )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_D_SUB_COMPLETE_PREFIX}1-{task_ids[0]}",
                name="complete_todo",
                arguments={
                    "task_id": task_ids[0],
                    "summary": "samples_df 30행 생성 + stats_df 6행 산출 + avg 별도 추출",
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 3: save_artifact(parquet) x2 + complete_todo(2).
    if not has_parquet and len(task_ids) >= 2:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_D_SUB_PARQUET_PREFIX}samples-{uuid.uuid4().hex[:8]}",
                name="save_artifact",
                arguments={
                    "filename": "samples.parquet",
                    "kind": "parquet",
                    "source": "$samples_df",
                },
            )
        )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_D_SUB_PARQUET_PREFIX}stats-{uuid.uuid4().hex[:8]}",
                name="save_artifact",
                arguments={
                    "filename": "stats.parquet",
                    "kind": "parquet",
                    "source": "$stats_df",
                },
            )
        )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_D_SUB_COMPLETE_PREFIX}2-{task_ids[1]}",
                name="complete_todo",
                arguments={
                    "task_id": task_ids[1],
                    "summary": "samples.parquet · stats.parquet 저장 완료",
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 4: save_artifact(spec.json) + display_chart + complete_todo(3).
    if not has_chart and len(task_ids) >= 3:
        spec_path = (
            f"result/{session_dir_name()}/{_current_turn_slot_name()}/charts.spec.json"
        )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_D_SUB_SPEC_PREFIX}{uuid.uuid4().hex[:8]}",
                name="save_artifact",
                arguments={
                    "filename": "charts.spec.json",
                    "kind": "json",
                    "content": json.dumps(_scenario_D_chart_spec(), ensure_ascii=False),
                },
            )
        )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_D_SUB_CHART_PREFIX}{uuid.uuid4().hex[:8]}",
                name="display_chart",
                arguments={"source": spec_path, "title": "통계량 요약 차트"},
            )
        )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_D_SUB_COMPLETE_PREFIX}3-{task_ids[2]}",
                name="complete_todo",
                arguments={
                    "task_id": task_ids[2],
                    "summary": "charts.spec.json + 렌더된 charts.json 생성 완료",
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 5: complete_subagent — 모든 단계 완료 시.
    if completed >= 3:
        summary = (
            "Task Summary:\n"
            "- samples_df 30행 polars DataFrame 생성 + compute_summary_stats_df 호출\n"
            "- samples.parquet · stats.parquet 디스크 직렬화 (타입 보존)\n"
            "- charts.spec.json (6 차트 spec) 작성 후 display_chart 로 렌더링"
        )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_D_SUB_FINISH_PREFIX}{uuid.uuid4().hex[:8]}",
                name="complete_subagent",
                arguments={"summary": summary},
            )
        )
        yield DoneEvent()
        return

    # 안전 폴백 (이론상 도달하지 않음) — 즉시 종료.
    yield ToolCallEvent(
        call=ToolCall(
            id=f"{_D_SUB_FINISH_PREFIX}safe-{uuid.uuid4().hex[:8]}",
            name="complete_subagent",
            arguments={"summary": "분석 작업 중단 — 비정상 상태"},
        )
    )
    yield DoneEvent()


# =============================================================================
# Scenario E — composite (analyst → writer)
# =============================================================================

_E_ORCH_ADD_PREFIX = "mock-E-orch-add-"
_E_ORCH_DISPATCH_ANALYST_PREFIX = "mock-E-orch-dispatch-analyst-"
_E_ORCH_DISPATCH_WRITER_PREFIX = "mock-E-orch-dispatch-writer-"
_E_ORCH_COMPLETE_PREFIX = "mock-E-orch-complete-"


def _is_E_active(messages: list[Message], last_user: Message | None) -> bool:
    if _has_recent_tool_result(messages, _E_ORCH_ADD_PREFIX):
        return True
    return last_user is not None and _matches(last_user.content, _E_TRIGGERS)


async def _scenario_E_orchestrator(
    messages: list[Message],
) -> AsyncIterator[StreamEvent]:
    """오케스트레이터 6턴 흐름.

    1: ReasoningEvent(계획 수립) + add_todo(2)
    2: dispatch analyst_agent
    3: complete_todo(1)
    4: dispatch writer_agent (analyst summary embed)
    5: complete_todo(2)
    6: ReasoningEvent(종합) + 최종 markdown 응답
    """
    has_add = _has_recent_tool_result(messages, _E_ORCH_ADD_PREFIX)
    has_dispatch_analyst = _has_recent_tool_result(
        messages, _E_ORCH_DISPATCH_ANALYST_PREFIX
    )
    has_dispatch_writer = _has_recent_tool_result(
        messages, _E_ORCH_DISPATCH_WRITER_PREFIX
    )
    completed = _count_completes(messages, _E_ORCH_COMPLETE_PREFIX)
    task_ids = _extract_task_ids(messages, _E_ORCH_ADD_PREFIX)

    # 턴 1: 계획 수립 추론 → add_todo(2).
    # 단일 도구로 끝나지 않는 복합 요청임을 먼저 추론으로 분해한 뒤, 그 결론을 todo 계획에 반영한다.
    if not has_add:
        planning = (
            "사용자가 '종합 분석 보고서'를 요청했다. 이는 단일 도구 한 번으로 끝나지 않는다. "
            "(1) 데이터 통계 분석·시각화와 (2) 그 결과를 정리한 보고서 작성, 두 전문 영역으로 나뉜다. "
            "각각 analyst_agent 와 writer_agent 에 순차 위임해야 하므로, 먼저 이 2단계를 todo 계획으로 분해한다..."
        )
        for i in range(0, len(planning), 6):
            await asyncio.sleep(_MOCK_TOKEN_DELAY)
            yield ReasoningEvent(content=planning[i : i + 6])

        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_E_ORCH_ADD_PREFIX}{uuid.uuid4().hex[:8]}",
                name="add_todo",
                arguments={
                    "items": [
                        {
                            "description": "데이터 분석 단계 — analyst_agent 에 위임",
                            "tool_name": "call_sub_agent",
                        },
                        {
                            "description": "보고서 작성 단계 — writer_agent 에 위임",
                            "tool_name": "call_sub_agent",
                        },
                    ]
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 2: analyst_agent 위임.
    if not has_dispatch_analyst:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_E_ORCH_DISPATCH_ANALYST_PREFIX}{uuid.uuid4().hex[:8]}",
                name="call_sub_agent",
                arguments={
                    "agent_name": "analyst_agent",
                    "task": (
                        f"{_COMPOSITE_TASK_MARKER} 통계 계산 및 차트 시각화 — "
                        "임의 표본 24건에 대해 요약 통계를 계산하고 막대 차트로 표시하라."
                    ),
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 3: 첫 번째 todo 완료.
    if completed == 0 and task_ids:
        first_id = task_ids[0]
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_E_ORCH_COMPLETE_PREFIX}1-{first_id}",
                name="complete_todo",
                arguments={
                    "task_id": first_id,
                    "summary": "analyst_agent 완료 — 통계 계산 및 차트 시각화",
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 4: writer_agent 위임 (analyst summary embed).
    if not has_dispatch_writer:
        analyst_summary = (
            _latest_tool_content(messages, _E_ORCH_DISPATCH_ANALYST_PREFIX)
            or "(분석 요약 없음)"
        )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_E_ORCH_DISPATCH_WRITER_PREFIX}{uuid.uuid4().hex[:8]}",
                name="call_sub_agent",
                arguments={
                    "agent_name": "writer_agent",
                    "task": (
                        f"{_COMPOSITE_TASK_MARKER} 다음 분석 결과를 한국어 마크다운 "
                        f"리포트로 정리하라. 분석가 요약:\n\n{analyst_summary}"
                    ),
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 5: 두 번째 todo 완료.
    if completed == 1 and len(task_ids) >= 2:
        second_id = task_ids[1]
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_E_ORCH_COMPLETE_PREFIX}2-{second_id}",
                name="complete_todo",
                arguments={
                    "task_id": second_id,
                    "summary": "writer_agent 완료 — report.md 산출 및 패널 렌더링",
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 6: 최종 ReasoningEvent + markdown 응답.
    reasoning = (
        "두 sub-agent 의 결과를 사용자에게 통합 보고합니다. "
        "분석가의 통계 산출과 작성자의 리포트 생성을 한 응답으로 요약합니다..."
    )
    for i in range(0, len(reasoning), 6):
        await asyncio.sleep(_MOCK_TOKEN_DELAY)
        yield ReasoningEvent(content=reasoning[i : i + 6])

    reply = (
        "## 종합 분석 보고 완료\n\n"
        "두 sub-agent 의 작업이 모두 마무리되었습니다.\n\n"
        "### 1. 데이터 분석 (analyst_agent · data_summary skill)\n"
        "- compute_summary_stats 함수로 6개 지표 결정론적 계산\n"
        "- 결과는 우측 패널의 막대 차트로 확인 가능\n\n"
        "### 2. 보고서 작성 (writer_agent · report_writer skill)\n"
        "- 분석 결과를 한국어 마크다운으로 구조화\n"
        "- `report.md` 산출물 생성 및 사이드 패널에 렌더링\n\n"
        "전체 분석 보고서 작업이 정상적으로 마무리되었습니다."
    )
    for ch in reply:
        await asyncio.sleep(_MOCK_TOKEN_DELAY)
        yield DeltaEvent(content=ch)
    yield DoneEvent()


# --- E analyst sub-agent flow ------------------------------------------------

_E_ANALYST_ADD_PREFIX = "mock-E-analyst-add-"
_E_ANALYST_CALL_PREFIX = "mock-E-analyst-call-"
_E_ANALYST_PARQUET_PREFIX = "mock-E-analyst-parquet-"
_E_ANALYST_SPEC_PREFIX = "mock-E-analyst-spec-"
_E_ANALYST_CHART_PREFIX = "mock-E-analyst-chart-"
_E_ANALYST_COMPLETE_PREFIX = "mock-E-analyst-complete-"
_E_ANALYST_FINISH_PREFIX = "mock-E-analyst-finish-"


async def _scenario_E_analyst_sub(
    messages: list[Message],
) -> AsyncIterator[StreamEvent]:
    """E analyst sub — 신규 parquet + spec 파이프라인 (5턴).

    턴 1: add_todo(3)
    턴 2: exec_code (samples_df + corr_df + grouped_df) + call_function (stats_df)
          + complete_todo(1)
    턴 3: save_artifact(parquet) × 4 (samples / stats / corr / grouped) + complete_todo(2)
    턴 4: save_artifact(json, charts.spec.json) + display_chart + complete_todo(3)
    턴 5: complete_subagent
    """
    has_add = _has_recent_tool_result(messages, _E_ANALYST_ADD_PREFIX)
    has_call = _has_recent_tool_result(messages, _E_ANALYST_CALL_PREFIX)
    has_parquet = _has_recent_tool_result(messages, _E_ANALYST_PARQUET_PREFIX)
    has_chart = _has_recent_tool_result(messages, _E_ANALYST_CHART_PREFIX)
    task_ids = _extract_task_ids(messages, _E_ANALYST_ADD_PREFIX)
    completed = _count_completes(messages, _E_ANALYST_COMPLETE_PREFIX)

    # 턴 1: add_todo(3).
    if not has_add:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_E_ANALYST_ADD_PREFIX}{uuid.uuid4().hex[:8]}",
                name="add_todo",
                arguments={
                    "items": [
                        {
                            "description": "samples_df + corr_df + grouped_df 생성 + 통계 계산"
                        },
                        {
                            "description": "samples.parquet · stats.parquet · corr.parquet · grouped.parquet 직렬화"
                        },
                        {
                            "description": "charts.spec.json 작성 후 display_chart 호출 (7 차트)"
                        },
                    ]
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 2: exec_code + call_function + complete_todo(1).
    if not has_call and task_ids:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"mock-E-analyst-exec-{uuid.uuid4().hex[:8]}",
                name="exec_code",
                arguments={"code": _build_E_dataframes_code(n=24)},
            )
        )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_E_ANALYST_CALL_PREFIX}{uuid.uuid4().hex[:8]}",
                name="call_function",
                arguments={
                    "qualified_name": "scripts.stats_df.compute_summary_stats_df",
                    "kwargs": {"data": "$value_list"},
                    "store_as": "stats_df",
                },
            )
        )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_E_ANALYST_COMPLETE_PREFIX}1-{task_ids[0]}",
                name="complete_todo",
                arguments={
                    "task_id": task_ids[0],
                    "summary": "samples_df(24행) + corr_df(4행) + grouped_df(4행) 생성 + stats_df 산출",
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 3: 4개 parquet 직렬화 + complete_todo(2).
    if not has_parquet and len(task_ids) >= 2:
        for varname, filename in [
            ("samples_df", "samples.parquet"),
            ("stats_df", "stats.parquet"),
            ("corr_df", "corr.parquet"),
            ("grouped_df", "grouped.parquet"),
        ]:
            yield ToolCallEvent(
                call=ToolCall(
                    id=f"{_E_ANALYST_PARQUET_PREFIX}{varname}-{uuid.uuid4().hex[:8]}",
                    name="save_artifact",
                    arguments={
                        "filename": filename,
                        "kind": "parquet",
                        "source": f"${varname}",
                    },
                )
            )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_E_ANALYST_COMPLETE_PREFIX}2-{task_ids[1]}",
                name="complete_todo",
                arguments={
                    "task_id": task_ids[1],
                    "summary": "4개 parquet (samples · stats · corr · grouped) 저장 완료",
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 4: save_artifact(spec) + display_chart + complete_todo(3).
    if not has_chart and len(task_ids) >= 3:
        spec_path = (
            f"result/{session_dir_name()}/{_current_turn_slot_name()}/charts.spec.json"
        )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_E_ANALYST_SPEC_PREFIX}{uuid.uuid4().hex[:8]}",
                name="save_artifact",
                arguments={
                    "filename": "charts.spec.json",
                    "kind": "json",
                    "content": json.dumps(_scenario_E_chart_spec(), ensure_ascii=False),
                },
            )
        )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_E_ANALYST_CHART_PREFIX}{uuid.uuid4().hex[:8]}",
                name="display_chart",
                arguments={"source": spec_path, "title": "종합 분석 차트 (7종)"},
            )
        )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_E_ANALYST_COMPLETE_PREFIX}3-{task_ids[2]}",
                name="complete_todo",
                arguments={
                    "task_id": task_ids[2],
                    "summary": "charts.spec.json (7 차트) + 렌더된 charts.json 생성 완료",
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 5: complete_subagent.
    if completed >= 3:
        summary = (
            "Task Summary:\n"
            "- 24행 samples_df + 보조 DataFrame 3종 polars 생성\n"
            "- 4개 parquet 디스크 직렬화 (타입 보존)\n"
            "- 7 차트 spec 작성 후 렌더링 (페이지네이션 검증: 6+1)"
        )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_E_ANALYST_FINISH_PREFIX}{uuid.uuid4().hex[:8]}",
                name="complete_subagent",
                arguments={"summary": summary},
            )
        )
        yield DoneEvent()
        return

    yield ToolCallEvent(
        call=ToolCall(
            id=f"{_E_ANALYST_FINISH_PREFIX}safe-{uuid.uuid4().hex[:8]}",
            name="complete_subagent",
            arguments={"summary": "E analyst 비정상 종료"},
        )
    )
    yield DoneEvent()


# --- E writer sub-agent flow -------------------------------------------------

_E_WRITER_SAVE_PREFIX = "mock-E-writer-save-"
_E_WRITER_MD_PREFIX = "mock-E-writer-md-"
_E_WRITER_GALLERY_PREFIX = "mock-E-writer-gallery-"
_E_WRITER_FINISH_PREFIX = "mock-E-writer-finish-"

_E_REPORT_BODY = """# 종합 분석 리포트

## 요약

[가정] 표본 24건에 대해 데이터 분석 sub-agent (analyst_agent) 가 결정론 함수
`compute_summary_stats` 를 호출해 6개 핵심 지표를 산출했다. 본 문서는 그 결과를
사용자에게 구조화된 마크다운으로 정리한 통합 보고서다.

## 핵심 지표

| 지표 | 값 | 비고 |
|---|---|---|
| count | 24 | 표본 개수 |
| mean | 8.1 | 중심 경향 |
| median | 7.9 | 중앙값 |
| stdev | 5.2 | 표준편차 |
| min | -1.2 | 최솟값 |
| max | 17.4 | 최댓값 |

## 인사이트

- **양의 분포 경향** — mean 과 median 모두 양수 영역에 위치
- **중간 수준 변동성** — stdev 가 mean 의 ~64% 수준으로 산포가 보통
- **이상치 가능성** — min/max 사이 범위(~18.6)가 stdev 의 3.5배 이상

## 후속 액션

```text
1. 표본 크기를 100건 이상으로 확장해 재계산
2. 박스 플롯·히스토그램 시각화로 분포 형태 확인
3. 이상치 후보를 식별해 별도 검증 절차 진행
```

> 본 리포트는 Mock provider 의 composite 시나리오에서 생성된 데모 산출물이다.
"""


async def _scenario_E_writer_sub(
    messages: list[Message],
) -> AsyncIterator[StreamEvent]:
    """E writer sub — save_artifact + display_markdown → display_image(10장) → complete_subagent.

    이미지 갤러리는 패널의 무한 스크롤·N/M 카운터·라이트박스 UX 를 한 번에 검증한다.
    """
    has_save = _has_recent_tool_result(messages, _E_WRITER_SAVE_PREFIX)
    has_gallery = _has_recent_tool_result(messages, _E_WRITER_GALLERY_PREFIX)

    # 턴 1: report.md 저장 + display_markdown.
    if not has_save:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_E_WRITER_SAVE_PREFIX}{uuid.uuid4().hex[:8]}",
                name="save_artifact",
                arguments={
                    "filename": "report.md",
                    "content": _E_REPORT_BODY,
                    "kind": "markdown",
                },
            )
        )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_E_WRITER_MD_PREFIX}{uuid.uuid4().hex[:8]}",
                name="display_markdown",
                arguments={
                    "source": f"result/{session_dir_name()}/{_current_turn_slot_name()}/report.md",
                    "title": "종합 분석 리포트",
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 2: 색상 카드 10장 갤러리 — list 형태 display_image 검증.
    if not has_gallery:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_E_WRITER_GALLERY_PREFIX}{uuid.uuid4().hex[:8]}",
                name="display_image",
                arguments={"images": _save_gallery_artifacts()},
            )
        )
        yield DoneEvent()
        return

    # 턴 3: 완료 보고.
    summary = (
        "Task Summary:\n"
        "- report.md 생성 (요약·핵심 지표 표·인사이트 3건·후속 액션·인용)\n"
        "- ArtifactMarkdown 으로 리포트 렌더링, 색상 카드 10장 갤러리 추가 표시"
    )
    yield ToolCallEvent(
        call=ToolCall(
            id=f"{_E_WRITER_FINISH_PREFIX}{uuid.uuid4().hex[:8]}",
            name="complete_subagent",
            arguments={"summary": summary},
        )
    )
    yield DoneEvent()


# =============================================================================
# Scenario F — parallel (analyst ∥ writer 동시 위임)
# =============================================================================
# sub-agent 흐름은 D analyst·E writer 를 그대로 재사용한다 (composite marker 미부여 →
# analyst 는 D, writer 는 E writer 로 라우팅). 오케스트레이터만 call_sub_agents_parallel
# 로 두 작업을 동시에 위임해 병렬 트레일 동시 렌더를 검증한다.

_F_ORCH_PARALLEL_PREFIX = "mock-F-orch-parallel-"


def _is_F_active(messages: list[Message], last_user: Message | None) -> bool:
    if _has_recent_tool_result(messages, _F_ORCH_PARALLEL_PREFIX):
        return True
    return last_user is not None and _matches(last_user.content, _F_TRIGGERS)


async def _scenario_F_orchestrator(
    messages: list[Message],
) -> AsyncIterator[StreamEvent]:
    """오케스트레이터 2턴: 1턴=병렬 위임, 2턴=통합 보고.

    1: ReasoningEvent(독립성 판단) + call_sub_agents_parallel(analyst, writer)
    2: 통합 tool_result 수신 후 ReasoningEvent + markdown 최종 보고
    """
    has_parallel = _has_recent_tool_result(messages, _F_ORCH_PARALLEL_PREFIX)

    # 턴 1: 두 작업이 독립적임을 추론 → 병렬 위임.
    if not has_parallel:
        planning = (
            "사용자가 '병렬 분석'을 요청했다. (1) 표본 데이터 통계·시각화와 "
            "(2) 개요 리포트 작성은 서로의 결과에 의존하지 않는 독립 작업이다. "
            "따라서 call_sub_agent 로 하나씩 기다리지 않고 call_sub_agents_parallel 로 "
            "analyst_agent 와 writer_agent 에 동시 위임한다..."
        )
        for i in range(0, len(planning), 6):
            await asyncio.sleep(_MOCK_TOKEN_DELAY)
            yield ReasoningEvent(content=planning[i : i + 6])

        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_F_ORCH_PARALLEL_PREFIX}{uuid.uuid4().hex[:8]}",
                name="call_sub_agents_parallel",
                arguments={
                    "tasks": [
                        {
                            "agent_name": "analyst_agent",
                            "task": "임의 표본 데이터의 요약 통계를 계산하고 막대·라인 차트로 시각화하라.",
                        },
                        {
                            "agent_name": "writer_agent",
                            "task": "데이터 분석 개요를 한국어 마크다운 리포트로 작성하라.",
                        },
                    ]
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 2: 통합 tool_result 수신 후 최종 보고.
    summary = (
        _latest_tool_content(messages, _F_ORCH_PARALLEL_PREFIX) or "(병렬 요약 없음)"
    )
    reasoning = (
        "두 서브 에이전트가 동시에 작업을 마쳤다. 통합 tool_result 의 두 요약 블록을 "
        "사용자에게 한 응답으로 정리한다..."
    )
    for i in range(0, len(reasoning), 6):
        await asyncio.sleep(_MOCK_TOKEN_DELAY)
        yield ReasoningEvent(content=reasoning[i : i + 6])

    reply = (
        "## 병렬 분석 완료\n\n"
        "두 서브 에이전트(analyst · writer)가 **동시에** 작업을 마쳤습니다.\n\n"
        "**통합 결과 요약**\n"
        f"```\n{summary}\n```\n\n"
        "우측 패널에서 분석 차트와 리포트를 각각 확인할 수 있습니다."
    )
    for ch in reply:
        await asyncio.sleep(_MOCK_TOKEN_DELAY)
        yield DeltaEvent(content=ch)
    yield DoneEvent()


# =============================================================================
# 공용 헬퍼
# =============================================================================


def _detect_sub_agent_name(messages: list[Message]) -> str | None:
    """system 메시지에 "당신은 '<name>' 서브 에이전트" 헤더가 있으면 agent_name 추출."""
    if not messages or messages[0].role != "system":
        return None
    system_text = messages[0].content
    marker_pos = system_text.find(_SUB_AGENT_MARKER)
    if marker_pos == -1:
        return None
    start = marker_pos + len(_SUB_AGENT_MARKER)
    end = system_text.find("'", start)
    if end == -1:
        return None
    return system_text[start:end]


def _find_last_user(messages: list[Message]) -> Message | None:
    for m in reversed(messages):
        if m.role == "user":
            return m
    return None


def _find_sub_task_text(messages: list[Message]) -> str | None:
    """sub-agent context 에서 task 텍스트 (첫 user 메시지) 를 반환한다."""
    for m in messages:
        if m.role == "user":
            return m.content
    return None


def _matches(text: str, triggers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(t.lower() in lowered for t in triggers)


def _has_recent_tool_result(messages: list[Message], prefix: str) -> bool:
    """현재 턴 안에서 특정 prefix 의 tool_result 가 이미 있는지 확인한다.

    "현재 턴" 은 마지막 user 메시지 이후의 슬라이스로 정의 — harness 가 매 턴
    user 메시지를 messages 끝에 추가하므로 이 경계가 정확하다.
    """
    last_user_idx = -1
    for i, m in enumerate(messages):
        if m.role == "user":
            last_user_idx = i
    if last_user_idx < 0:
        return False
    for m in messages[last_user_idx + 1 :]:
        if m.role == "tool" and (m.tool_call_id or "").startswith(prefix):
            return True
    return False


def _latest_tool_content(messages: list[Message], prefix: str) -> str | None:
    """특정 prefix 의 가장 최근 tool_result content 를 반환한다."""
    for m in reversed(messages):
        if m.role == "tool" and (m.tool_call_id or "").startswith(prefix):
            return m.content
    return None


def _extract_task_ids(messages: list[Message], add_todo_prefix: str) -> list[str]:
    """add_todo tool_result 에서 등록된 task_id (8자 hex) 들을 순서대로 추출."""
    out: list[str] = []
    for m in messages:
        if m.role == "tool" and (m.tool_call_id or "").startswith(add_todo_prefix):
            out.extend(re.findall(r"'([0-9a-f]{8})'", m.content))
    return out


def _count_completes(messages: list[Message], complete_prefix: str) -> int:
    """complete_todo 의 tool_result 개수를 센다 — task_id 별 카운트가 아닌 호출 수."""
    count = 0
    for m in messages:
        if m.role == "tool" and (m.tool_call_id or "").startswith(complete_prefix):
            count += 1
    return count


def _extract_artifact_path(messages: list[Message], save_prefix: str) -> str | None:
    """save_artifact tool_result content 에서 'result/...' 경로를 파싱해 반환한다.

    save_artifact 는 성공 시 '저장 완료: result/<session>/<ts>/<file>' 형식으로 응답한다.
    """
    content = _latest_tool_content(messages, save_prefix)
    if content and content.startswith("저장 완료: "):
        return content[len("저장 완료: ") :].split("\n")[0].strip()
    return None


def _compose_reply(last_user: Message | None) -> str:
    """A echo 폴백 응답."""
    if last_user is None:
        return "안녕하세요. 무엇을 도와드릴까요?"
    return (
        f"[mock] '{last_user.content}' 라고 하셨네요. "
        "실제 LLM 이 연결되면 이 자리에 답변이 옵니다."
    )


# =============================================================================
# 시각화 데모 데이터 — D/E 시나리오의 display_chart / display_image 항목
# =============================================================================


def _build_samples_df_code(n: int, x_step: float, noise: float) -> str:
    """exec_code 에 전달할 polars DataFrame 생성 코드 문자열.

    samples_df 컬럼: idx (Int64), value (Float64), anomaly_score (Float64),
    group (Utf8: A/B/C 순환). group 은 color 채널(레전드)용 — 그룹별 다중 시리즈
    차트와 레전드 컨트롤(순서·색상·Hide·Filter) 데모를 위해 부여한다.
    value_list 도 namespace 에 함께 저장 — call_function 의 list[float] 인자로 사용.
    """
    return (
        "import polars as pl\n"
        f"_n, _step, _noise = {n}, {x_step}, {noise}\n"
        "_values = [round(i * _step + ((i * 7) % 11 - 5) * _noise, 3) for i in range(_n)]\n"
        "_anomaly = [round(((i * 7) % 11 - 5) * _noise / 4.0, 3) for i in range(_n)]\n"
        "_groups = [['A', 'B', 'C'][i % 3] for i in range(_n)]\n"
        "samples_df = pl.DataFrame({\n"
        "    'idx': list(range(_n)),\n"
        "    'value': _values,\n"
        "    'anomaly_score': _anomaly,\n"
        "    'group': _groups,\n"
        "})\n"
        "value_list = samples_df['value'].to_list()\n"
        "print(f'samples_df: shape={samples_df.shape}, value_list len={len(value_list)}')"
    )


def _build_E_dataframes_code(n: int) -> str:
    """E 시나리오용 — samples_df + corr_df + grouped_df 를 한 번에 생성.

    corr_df: 2x2 상관계수 heatmap 용 (row, col, value)
    grouped_df: 그룹별 분기 평균 (group, quarter, value)
    """
    return (
        "import polars as pl\n"
        f"_n = {n}\n"
        "_values = [round(i * 0.7 + ((i * 5) % 9 - 4) * 0.3, 3) for i in range(_n)]\n"
        "_anomaly = [round(((i * 5) % 9 - 4) * 0.3 / 4.0, 3) for i in range(_n)]\n"
        "samples_df = pl.DataFrame({\n"
        "    'idx': list(range(_n)),\n"
        "    'value': _values,\n"
        "    'anomaly_score': _anomaly,\n"
        "})\n"
        "value_list = samples_df['value'].to_list()\n"
        "corr_df = pl.DataFrame({\n"
        "    'row': ['mean', 'mean', 'stdev', 'stdev'],\n"
        "    'col': ['mean', 'stdev', 'mean', 'stdev'],\n"
        "    'value': [1.0, 0.32, 0.32, 1.0],\n"
        "})\n"
        "grouped_df = pl.DataFrame({\n"
        "    'group': ['A', 'A', 'B', 'B'],\n"
        "    'quarter': ['Q1', 'Q2', 'Q1', 'Q2'],\n"
        "    'value': [7.5, 8.2, 6.9, 7.8],\n"
        "})\n"
        "print(f'samples_df {samples_df.shape}, corr_df {corr_df.shape}, grouped_df {grouped_df.shape}')"
    )


def _scenario_D_chart_spec() -> dict[str, Any]:
    """D 시나리오 — 6 차트 ChartSpecV1 (bar/line/scatter/box + 그룹 scatter/ecdf).

    samples.parquet (idx, value, anomaly_score, group) + stats.parquet (metric, value)
    참조. 마지막 2개는 color 채널(group)을 써 레전드 컨트롤(순서·색상·Hide·Filter)을
    검증한다 — 그룹 scatter 는 점 기반(brush + 레전드 Filter), 그룹 ecdf 는 line+overlay.
    """
    return {
        "version": "1",
        "charts": [
            {
                "mark": "bar",
                "title": "요약 통계량 (stats_df)",
                "data": {"source": "stats.parquet"},
                "encoding": {
                    "x": {"field": "metric", "type": "nominal", "title": "지표"},
                    "y": {"field": "value", "type": "quantitative", "title": "값"},
                },
            },
            {
                "mark": "line",
                "title": "samples 추세",
                "data": {"source": "samples.parquet"},
                "encoding": {
                    "x": {"field": "idx", "type": "quantitative", "title": "인덱스"},
                    "y": {"field": "value", "type": "quantitative", "title": "값"},
                },
            },
            {
                "mark": "scatter",
                "title": "samples vs 이상치 점수",
                "data": {"source": "samples.parquet"},
                "encoding": {
                    "x": {"field": "value", "type": "quantitative", "title": "값"},
                    "y": {
                        "field": "anomaly_score",
                        "type": "quantitative",
                        "title": "이상치 점수",
                    },
                },
            },
            {
                "mark": "box",
                "title": "값 분포 박스플롯",
                "data": {"source": "samples.parquet"},
                "encoding": {
                    "y": {"field": "value", "type": "quantitative", "title": "값"},
                },
            },
            {
                "mark": "scatter",
                "title": "그룹별 산점도 (레전드 데모)",
                "data": {"source": "samples.parquet"},
                "encoding": {
                    "x": {"field": "value", "type": "quantitative", "title": "값"},
                    "y": {
                        "field": "anomaly_score",
                        "type": "quantitative",
                        "title": "이상치 점수",
                    },
                    "color": {"field": "group", "type": "nominal", "title": "그룹"},
                },
            },
            {
                "mark": "ecdf",
                "title": "그룹별 누적분포 (레전드 데모)",
                "data": {"source": "samples.parquet"},
                "encoding": {
                    "x": {"field": "value", "type": "quantitative", "title": "값"},
                    "color": {"field": "group", "type": "nominal", "title": "그룹"},
                },
            },
        ],
    }


def _scenario_E_chart_spec() -> dict[str, Any]:
    """E 시나리오 — 7 차트 ChartSpecV1. 페이지네이션(6+1) 검증."""
    return {
        "version": "1",
        "charts": [
            {
                "mark": "bar",
                "title": "요약 통계량 (composite)",
                "data": {"source": "stats.parquet"},
                "encoding": {
                    "x": {"field": "metric", "type": "nominal", "title": "지표"},
                    "y": {"field": "value", "type": "quantitative", "title": "값"},
                },
            },
            {
                "mark": "line",
                "title": "samples 시계열",
                "data": {"source": "samples.parquet"},
                "encoding": {
                    "x": {"field": "idx", "type": "quantitative", "title": "인덱스"},
                    "y": {"field": "value", "type": "quantitative", "title": "값"},
                },
            },
            {
                "mark": "scatter",
                "title": "samples 산점도",
                "data": {"source": "samples.parquet"},
                "encoding": {
                    "x": {"field": "value", "type": "quantitative", "title": "값"},
                    "y": {
                        "field": "anomaly_score",
                        "type": "quantitative",
                        "title": "이상치",
                    },
                },
            },
            {
                "mark": "box",
                "title": "값 분포 박스플롯",
                "data": {"source": "samples.parquet"},
                "encoding": {
                    "y": {"field": "value", "type": "quantitative", "title": "값"},
                },
            },
            {
                "mark": "histogram",
                "title": "값 분포 히스토그램",
                "data": {"source": "samples.parquet"},
                "encoding": {
                    "x": {
                        "field": "value",
                        "type": "quantitative",
                        "bin": True,
                        "title": "구간",
                    },
                },
            },
            {
                "mark": "heatmap",
                "title": "상관 히트맵 (mean × stdev)",
                "data": {"source": "corr.parquet"},
                "encoding": {
                    "x": {"field": "col", "type": "nominal", "title": "지표 X"},
                    "y": {"field": "row", "type": "nominal", "title": "지표 Y"},
                    "color": {
                        "field": "value",
                        "type": "quantitative",
                        "title": "상관계수",
                    },
                },
            },
            {
                "mark": "bar",
                "title": "그룹별 분기 평균 비교",
                "data": {"source": "grouped.parquet"},
                "encoding": {
                    "x": {"field": "quarter", "type": "nominal", "title": "분기"},
                    "y": {"field": "value", "type": "quantitative", "title": "평균"},
                    "color": {"field": "group", "type": "nominal", "title": "그룹"},
                },
            },
        ],
    }


def _save_gallery_artifacts() -> list[dict[str, Any]]:
    """색상 카드 10장 SVG 를 result 슬롯에 저장하고 display_image source 경로 목록을 반환한다.

    시나리오 C 의 _ensure_favicon_artifact() 와 동일한 디스크 저장 패턴을 따른다.
    """
    palette = [
        ("#FF6B6B", "01"),
        ("#FFA94D", "02"),
        ("#FFD43B", "03"),
        ("#69DB7C", "04"),
        ("#4DABF7", "05"),
        ("#9775FA", "06"),
        ("#F783AC", "07"),
        ("#63E6BE", "08"),
        ("#FFC078", "09"),
        ("#74C0FC", "10"),
    ]
    slot = artifact_slot()
    items: list[dict[str, Any]] = []
    for color, label in palette:
        filename = f"color-card-{label}.svg"
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 200">'
            f'<rect width="320" height="200" fill="{color}"/>'
            '<text x="160" y="115" font-family="sans-serif" font-size="56" '
            f'fill="white" text-anchor="middle" font-weight="700">{label}</text>'
            "</svg>"
        )
        (slot / filename).write_text(svg, encoding="utf-8")
        src = f"result/{session_dir_name()}/{slot.name}/{filename}"
        items.append(
            {
                "source": src,
                "alt": f"색상 카드 {label}",
                "caption": f"갤러리 카드 #{label} — {color}",
            }
        )
    return items
