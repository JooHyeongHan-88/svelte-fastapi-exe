"""Mock LLM provider — 실제 LLM 없이 harness/UI 를 검증하기 위한 가짜 응답기.

시나리오는 5개 카테고리로 분류된다. 각 시나리오는 사용자가 특정 트리거 문구를
입력하면 해당 UI/Harness 요소를 결정론적으로 발동시킨다.

============================================================
CATEGORY A — UI 표현 검증
============================================================
    A1. reasoning_block       trigger="생각해", "추론"
        검증: ReasoningEvent 청크 → 접을 수 있는 ReasoningBlock 토글
    A2. ask_user_text         trigger="자유 질문", "ask text"
        검증: AskUserCard input_type=text (자유 입력만)
    A3. ask_user_choice       trigger="기간 선택", "기간을 골라"
        검증: AskUserCard input_type=choice (옵션 버튼만)
    A4. ask_user_both         trigger="데이터 좀 보여줘", "모호한 요청"
        검증: AskUserCard input_type=both (옵션+자유입력)
    A5. markdown_echo         (어떤 트리거도 매칭 안 되면)
        검증: 평문 echo — 기본 markdown 렌더링

============================================================
CATEGORY B — SKILL 라우팅 검증
============================================================
    B1. skill_time_lookup     trigger="지금 몇 시", "현재 시각"
        검증: SkillActiveEvent(time_lookup) → now 도구 → 시각 응답
    B2. skill_report_planner  trigger="보고서", "리포트"
        검증: SkillActiveEvent(report_generator) → add_todo 3단계 플래너

============================================================
CATEGORY C — TOOL 실행 검증
============================================================
    C1. tool_slot_guard       trigger="검색", "데이터 조회"
        검증: demo_search 를 빈 인자로 호출 → harness guard → AskUserEvent
    C2. tool_todo_lifecycle   trigger="전체 보고서", "full report"
        검증: add_todo 3개 + complete_todo 순차 → TodoProgress PENDING→COMPLETED

============================================================
CATEGORY D — 서브 에이전트 위임 검증
============================================================
    D1. sub_explicit_coding   trigger="코딩 에이전트", "코드 리팩토링"
        검증: Case 2 명시 위임 — call_sub_agent(coding_agent)
    D2. sub_explicit_research trigger="리서치 에이전트", "조사 에이전트"
        검증: Case 2 명시 위임 — call_sub_agent(research_agent)
    D3. sub_chain             trigger="전체 분석", "full analysis"
        검증: coding_agent → research_agent 순차 위임 (체이닝)
    D4. sub_inner_now         (sub-agent context, D1/D2/D3 의 위임 후)
        검증: 서브 에이전트 내부에서 now 도구 1회 + Task Summary 종료

============================================================
CATEGORY E — 복합 통합 시나리오 (신규)
============================================================
    E1. composite_full_demo   trigger="종합 시연", "전체 시연", "full demo"
        검증: 한 사용자 turn 안에서 다음 흐름을 시연한다.
          1) 오케스트레이터가 add_todo 로 2단계 plan 등록 (sub-agent 단위 todo)
          2) call_sub_agent(research_agent) — sub-agent 안에서
             SkillActiveEvent(data_analysis) → ReasoningEvent → add_todo 3개 →
             complete_todo × 3 → complete_subagent
          3) 오케스트레이터가 첫 todo complete
          4) call_sub_agent(coding_agent) — sub-agent 안에서
             SkillActiveEvent(code_review) → ReasoningEvent → add_todo 3개 →
             complete_todo × 3 → complete_subagent
          5) 오케스트레이터가 두 번째 todo complete
          6) ReasoningEvent + DeltaEvent 로 통합 보고
        검증되는 UI: 메인 todo · agentTrail · sub-agent 슬롯 안 skill 뱃지 ·
                     sub-agent 안 ReasoningBlock · sub-agent 안 todo ·
                     최종 markdown 보고
"""

import asyncio
import re
import uuid
from collections.abc import AsyncIterator

from agent.models import (
    DeltaEvent,
    DoneEvent,
    Message,
    ReasoningEvent,
    SkillActiveEvent,
    StreamEvent,
    ToolCall,
    ToolCallEvent,
    ToolSpec,
)
from agent.registries.tools import ASK_USER

# 스트리밍 체감을 위한 토큰 간 지연 (초).
_MOCK_TOKEN_DELAY = 0.02

# ============================================================
# Category A — UI 표현 검증 트리거
# ============================================================
_REASONING_TRIGGERS = ("생각해", "생각 해", "think", "reason", "추론")
_ASK_TEXT_TRIGGERS = ("자유 질문", "ask text", "text 모드")
_ASK_CHOICE_TRIGGERS = ("기간 선택", "기간을 골라", "choice 모드", "ask choice")
_ASK_BOTH_TRIGGERS = ("데이터 좀 보여줘", "모호한 요청", "ask both", "both 모드")

# ============================================================
# Category B — SKILL 라우팅 검증 트리거
# ============================================================
_NOW_TRIGGERS = (
    "몇 시",
    "지금 시간",
    "현재 시각",
    "what time",
    "current time",
    "now()",
)
_REPORT_TRIGGERS = ("보고서", "리포트", "report")

# ============================================================
# Category C — TOOL 실행 검증 트리거
# ============================================================
_SEARCH_TRIGGERS = ("검색", "search", "데이터 조회")
_FULL_REPORT_TRIGGERS = ("전체 보고서", "full report")

# ============================================================
# Category D — 서브 에이전트 위임 검증 트리거
# ============================================================
# Case 2 — 명시 위임. 가장 먼저 검사돼야 다른 트리거에 흡수되지 않는다.
_CODING_AGENT_TRIGGERS = ("코딩 에이전트", "coding_agent", "코드 리팩토링")
_RESEARCH_AGENT_TRIGGERS = ("리서치 에이전트", "research_agent", "조사 에이전트")
# Case 2 + 체이닝 — 한 사용자 입력으로 두 에이전트 순차 위임.
_CHAIN_TRIGGERS = ("전체 분석", "full analysis")

# 서브 에이전트 분기 marker — _compose_sub_agent_system_prompt 가 항상 포함.
_SUB_AGENT_MARKER = "당신은 '"

# ============================================================
# Category E — 복합 통합 시나리오 트리거 + 내부 marker
# ============================================================
_COMPOSITE_TRIGGERS = ("종합 시연", "전체 시연", "full demo", "복합 시연")

# 오케스트레이터가 서브 에이전트에게 위임할 때 task 텍스트에 포함시키는 marker.
# sub-agent context 안의 mock 이 이 marker 를 보면 composite 흐름으로 분기한다.
# (일반 D 카테고리 sub-agent 시나리오와 결정론적으로 구분하기 위함.)
_COMPOSITE_TASK_MARKER = "[E1-composite]"


class MockProvider:
    """LLM 없이 UI/Harness 를 검증하기 위한 결정론 가짜 프로바이더.

    분기 우선순위 (위에서부터 검사):
        1) sub-agent context 여부 (system marker 로 판별)
            → composite sub task marker 가 있으면 E1 sub
            → 그 외엔 D4 generic sub
        2) E1 composite orchestrator (트리거 매칭)
        3) D3 chain (트리거 매칭)
        4) D1/D2 explicit delegation (트리거 매칭)
        5) 위임 결과 받은 다음 루프 — 통합 보고
        6) B1 now skill
        7) C2 full_report
        8) B2 report planner
        9) C1 search slot guard
        10) A2~A4 ask_user 3-mode
        11) ask_user 답변 받은 다음 루프
        12) A1 reasoning
        13) A5 echo (기본)
    """

    async def astream(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> AsyncIterator[StreamEvent]:
        del tools  # mock 은 도구 스펙을 참조하지 않음

        last_user = _find_last_user(messages)

        # ───────────────────────────────────────────────────────────────
        # 1) 서브 에이전트 컨텍스트 — system marker 로 결정론 판별
        # ───────────────────────────────────────────────────────────────
        sub_name = _detect_sub_agent_name(messages)
        if sub_name is not None:
            if _is_composite_sub_context(messages):
                async for event in _composite_sub_scenario(messages, sub_name):
                    yield event
                return
            async for event in _sub_agent_scenario(messages, sub_name):
                yield event
            return

        # ───────────────────────────────────────────────────────────────
        # 2) Category E — 복합 통합 시나리오 (오케스트레이터 측)
        # ───────────────────────────────────────────────────────────────
        if last_user is not None and _matches(last_user.content, _COMPOSITE_TRIGGERS):
            async for event in _composite_orch_scenario(messages):
                yield event
            return

        # ───────────────────────────────────────────────────────────────
        # 3) Category D3 — chain 위임
        # ───────────────────────────────────────────────────────────────
        if last_user is not None and _matches(last_user.content, _CHAIN_TRIGGERS):
            async for event in _chain_scenario(messages, last_user):
                yield event
            return

        # ───────────────────────────────────────────────────────────────
        # 4) Category D1/D2 — 명시 위임 (Case 2)
        # ───────────────────────────────────────────────────────────────
        already_dispatched = _has_recent_tool_result(messages, "mock-dispatch-")
        if last_user is not None and not already_dispatched:
            if _matches(last_user.content, _CODING_AGENT_TRIGGERS):
                yield ToolCallEvent(
                    call=ToolCall(
                        id=f"mock-dispatch-coding-{uuid.uuid4().hex[:8]}",
                        name="call_sub_agent",
                        arguments={
                            "agent_name": "coding_agent",
                            "task": last_user.content,
                        },
                    )
                )
                yield DoneEvent()
                return
            if _matches(last_user.content, _RESEARCH_AGENT_TRIGGERS):
                yield ToolCallEvent(
                    call=ToolCall(
                        id=f"mock-dispatch-research-{uuid.uuid4().hex[:8]}",
                        name="call_sub_agent",
                        arguments={
                            "agent_name": "research_agent",
                            "task": last_user.content,
                        },
                    )
                )
                yield DoneEvent()
                return

        # 5) 위임 결과를 받은 다음 루프 — 자연어 최종 보고.
        if already_dispatched:
            async for event in _orchestrator_final_report(messages):
                yield event
            return

        # ───────────────────────────────────────────────────────────────
        # 6) Category B1 — time_lookup skill / now tool
        # ───────────────────────────────────────────────────────────────
        already_called_now = _has_recent_tool_result(messages, "mock-now-")
        if (
            last_user is not None
            and _matches(last_user.content, _NOW_TRIGGERS)
            and not already_called_now
        ):
            yield ToolCallEvent(
                call=ToolCall(
                    id=f"mock-now-{uuid.uuid4().hex[:8]}",
                    name="now",
                    arguments={},
                )
            )
            yield DoneEvent()
            return

        # ───────────────────────────────────────────────────────────────
        # 7) Category C2 — full_report (add_todo + complete_todo 순차)
        # 시나리오 B2 보다 먼저 검사: "전체 보고서" 가 더 구체적인 트리거.
        # ───────────────────────────────────────────────────────────────
        if last_user is not None and _matches(last_user.content, _FULL_REPORT_TRIGGERS):
            async for event in _full_report_scenario(messages):
                yield event
            return

        # ───────────────────────────────────────────────────────────────
        # 8) Category B2 — report_generator skill / add_todo 플래너
        # ───────────────────────────────────────────────────────────────
        already_planned = _has_recent_tool_result(messages, "mock-todo-")
        if (
            last_user is not None
            and _matches(last_user.content, _REPORT_TRIGGERS)
            and not already_planned
        ):
            yield ToolCallEvent(
                call=ToolCall(
                    id=f"mock-todo-{uuid.uuid4().hex[:8]}",
                    name="add_todo",
                    arguments={
                        "items": [
                            {
                                "description": "매출 데이터 조회",
                                "tool_name": "fetch_sales",
                            },
                            {
                                "description": "보고서 본문 생성",
                                "tool_name": "render_report",
                            },
                            {"description": "이메일 발송", "tool_name": "send_email"},
                        ]
                    },
                )
            )
            yield DoneEvent()
            return

        # ───────────────────────────────────────────────────────────────
        # 9) Category C1 — demo_search 슬롯 가드
        # ───────────────────────────────────────────────────────────────
        already_searched = _has_recent_tool_result(messages, "mock-search-")
        if (
            last_user is not None
            and _matches(last_user.content, _SEARCH_TRIGGERS)
            and not already_searched
        ):
            # 인자를 비워서 호출 → harness guard 가 AskUserEvent 를 발동시킨다.
            yield ToolCallEvent(
                call=ToolCall(
                    id=f"mock-search-{uuid.uuid4().hex[:8]}",
                    name="demo_search",
                    arguments={},
                )
            )
            yield DoneEvent()
            return

        # ───────────────────────────────────────────────────────────────
        # 10) Category A2~A4 — ask_user sentinel 3 모드
        # ───────────────────────────────────────────────────────────────
        already_asked = _has_recent_tool_result(messages, "mock-ask-")
        if last_user is not None and not already_asked:
            if _matches(last_user.content, _ASK_BOTH_TRIGGERS):
                yield ToolCallEvent(
                    call=ToolCall(
                        id=f"mock-ask-both-{uuid.uuid4().hex[:8]}",
                        name=ASK_USER,
                        arguments={
                            "question": "어떤 데이터를 보여드릴까요?",
                            "options": [
                                "매출 데이터",
                                "재고 현황",
                                "주문 목록",
                                "고객 통계",
                            ],
                            "input_type": "both",
                        },
                    )
                )
                yield DoneEvent()
                return
            if _matches(last_user.content, _ASK_CHOICE_TRIGGERS):
                yield ToolCallEvent(
                    call=ToolCall(
                        id=f"mock-ask-choice-{uuid.uuid4().hex[:8]}",
                        name=ASK_USER,
                        arguments={
                            "question": "조회 기간을 선택해주세요.",
                            "options": ["오늘", "이번 주", "이번 달", "올해"],
                            "input_type": "choice",
                        },
                    )
                )
                yield DoneEvent()
                return
            if _matches(last_user.content, _ASK_TEXT_TRIGGERS):
                yield ToolCallEvent(
                    call=ToolCall(
                        id=f"mock-ask-text-{uuid.uuid4().hex[:8]}",
                        name=ASK_USER,
                        arguments={
                            "question": "구체적으로 어떤 내용이 궁금하신가요?",
                            "options": None,
                            "input_type": "text",
                        },
                    )
                )
                yield DoneEvent()
                return

        # 11) ask_user 답변 후 다음 루프 — 사용자 답변을 활용해 작업 완료 echo.
        if already_asked and last_user is not None:
            answer = last_user.content
            reply = (
                f"'{answer}' 으로 조회를 시작하겠습니다. "
                "(mock — 실제 LLM 연결 시 실제 데이터를 가져옵니다.)"
            )
            for ch in reply:
                await asyncio.sleep(_MOCK_TOKEN_DELAY)
                yield DeltaEvent(content=ch)
            yield DoneEvent()
            return

        # ───────────────────────────────────────────────────────────────
        # 12) Category A1 — reasoning
        # ───────────────────────────────────────────────────────────────
        if last_user is not None and _matches(last_user.content, _REASONING_TRIGGERS):
            async for event in _reasoning_scenario(last_user.content):
                yield event
            return

        # ───────────────────────────────────────────────────────────────
        # 13) Category A5 — 기본 echo
        # ───────────────────────────────────────────────────────────────
        reply = _compose_reply(last_user, messages)
        for ch in reply:
            await asyncio.sleep(_MOCK_TOKEN_DELAY)
            yield DeltaEvent(content=ch)

        yield DoneEvent()


# =============================================================================
# Category C2 — full_report 시나리오
# =============================================================================


def _full_report_scenario(
    messages: list[Message],
) -> AsyncIterator[StreamEvent]:
    """add_todo 등록 후 complete_todo 순차 실행으로 TodoProgress 전환을 시연."""
    full_todo_results = [
        m
        for m in messages
        if m.role == "tool" and (m.tool_call_id or "").startswith("mock-full-todo-")
    ]

    if not full_todo_results:

        async def _add() -> AsyncIterator[StreamEvent]:
            yield ToolCallEvent(
                call=ToolCall(
                    id=f"mock-full-todo-{uuid.uuid4().hex[:8]}",
                    name="add_todo",
                    arguments={
                        "items": [
                            {"description": "데이터 수집", "tool_name": "fetch_sales"},
                            {
                                "description": "분석 및 정리",
                                "tool_name": "render_report",
                            },
                            {"description": "최종 발송", "tool_name": "send_email"},
                        ]
                    },
                )
            )
            yield DoneEvent()

        return _add()

    task_ids: list[str] = []
    for tr in full_todo_results:
        task_ids.extend(re.findall(r"'([0-9a-f]{8})'", tr.content))

    completed_ids = {
        m.tool_call_id.replace("mock-full-complete-", "", 1)
        for m in messages
        if m.role == "tool" and (m.tool_call_id or "").startswith("mock-full-complete-")
    }
    pending_ids = [tid for tid in task_ids if tid not in completed_ids]

    async def _complete() -> AsyncIterator[StreamEvent]:
        if pending_ids:
            tid = pending_ids[0]
            yield ToolCallEvent(
                call=ToolCall(
                    id=f"mock-full-complete-{tid}",
                    name="complete_todo",
                    arguments={"task_id": tid, "summary": "완료"},
                )
            )
            yield DoneEvent()
            return

        reply = (
            "전체 보고서 작업이 모두 완료되었습니다. 3단계가 정상적으로 처리됐습니다."
        )
        for ch in reply:
            await asyncio.sleep(_MOCK_TOKEN_DELAY)
            yield DeltaEvent(content=ch)
        yield DoneEvent()

    return _complete()


# =============================================================================
# Category A1 — reasoning 시나리오
# =============================================================================


async def _reasoning_scenario(user_text: str) -> AsyncIterator[StreamEvent]:
    """ReasoningEvent 청크를 먼저 스트리밍한 뒤 DeltaEvent 로 응답한다."""
    reasoning = (
        f"사용자가 '{user_text}' 라고 입력했습니다. "
        "핵심 의도를 분석합니다... "
        "관련 컨텍스트를 검토합니다... "
        "최적의 답변 형식을 결정합니다..."
    )
    for i in range(0, len(reasoning), 5):
        await asyncio.sleep(_MOCK_TOKEN_DELAY)
        yield ReasoningEvent(content=reasoning[i : i + 5])

    reply = "깊이 생각해 보았습니다. 결론적으로 이 질문에 대한 답변을 드릴 수 있습니다."
    for ch in reply:
        await asyncio.sleep(_MOCK_TOKEN_DELAY)
        yield DeltaEvent(content=ch)

    yield DoneEvent()


# =============================================================================
# Category D — sub-agent 위임 시나리오
# =============================================================================


async def _chain_scenario(
    messages: list[Message], last_user: Message
) -> AsyncIterator[StreamEvent]:
    """D3 — coding_agent → research_agent → 통합 보고 (3단계 체이닝)."""
    coding_done = _has_recent_tool_result(messages, "mock-dispatch-coding-")
    research_done = _has_recent_tool_result(messages, "mock-dispatch-research-")

    if not coding_done:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"mock-dispatch-coding-{uuid.uuid4().hex[:8]}",
                name="call_sub_agent",
                arguments={
                    "agent_name": "coding_agent",
                    "task": f"코드 측면 분석 ({last_user.content})",
                },
            )
        )
        yield DoneEvent()
        return

    if not research_done:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"mock-dispatch-research-{uuid.uuid4().hex[:8]}",
                name="call_sub_agent",
                arguments={
                    "agent_name": "research_agent",
                    "task": f"배경 정보 조사 ({last_user.content})",
                },
            )
        )
        yield DoneEvent()
        return

    reply = (
        "두 서브 에이전트의 결과를 통합했습니다.\n\n"
        "- 코딩 에이전트: 코드 검토 및 리팩토링 후보 식별 완료\n"
        "- 리서치 에이전트: 배경 정보 수집 완료\n\n"
        "전체 분석이 마무리되었습니다."
    )
    for ch in reply:
        await asyncio.sleep(_MOCK_TOKEN_DELAY)
        yield DeltaEvent(content=ch)
    yield DoneEvent()


async def _sub_agent_scenario(
    messages: list[Message], agent_name: str
) -> AsyncIterator[StreamEvent]:
    """D4 — 서브 에이전트 일반 시나리오 (now 도구 1회 + Task Summary)."""
    already_called_now = _has_recent_tool_result(messages, "mock-sub-now-")
    if not already_called_now:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"mock-sub-now-{uuid.uuid4().hex[:8]}",
                name="now",
                arguments={},
            )
        )
        yield DoneEvent()
        return

    if agent_name == "coding_agent":
        reply = (
            "코드 부분 검토를 완료했습니다. 시각 도구로 작업 시점을 기록했고 "
            "안전한 리팩토링 후보 3곳, 네이밍 정리 2곳을 식별했습니다.\n\n"
            "Task Summary:\n"
            "- 코드 검토 완료 — 리팩토링 후보 3곳·네이밍 정리 2곳 식별\n"
            "- 다음 단계: 단위 테스트 추가 후 안전한 변경 진행 권장"
        )
    elif agent_name == "research_agent":
        reply = (
            "조사 작업을 마쳤습니다. 시각 도구로 현재 시점을 확인하고 관련 "
            "배경 정보를 정리했습니다.\n\n"
            "Task Summary:\n"
            "- 조사 주제 핵심 사실 수집 완료\n"
            "- 신뢰도: mock 환경 시뮬레이션 (실제 데이터 소스 미연결)"
        )
    else:
        reply = (
            f"{agent_name} 작업을 마쳤습니다.\n\n"
            "Task Summary:\n"
            f"- {agent_name} 위임 작업 완료"
        )

    for ch in reply:
        await asyncio.sleep(_MOCK_TOKEN_DELAY)
        yield DeltaEvent(content=ch)
    yield DoneEvent()


async def _orchestrator_final_report(
    messages: list[Message],
) -> AsyncIterator[StreamEvent]:
    """D1/D2 — 서브 에이전트 위임 결과를 받은 후 사용자에게 자연어 최종 보고."""
    last_dispatch = None
    for m in reversed(messages):
        if m.role == "tool" and (m.tool_call_id or "").startswith("mock-dispatch-"):
            last_dispatch = m
            break

    summary_text = last_dispatch.content if last_dispatch else "(결과 없음)"
    reply = f"서브 에이전트의 작업이 완료되었습니다.\n\n요약:\n{summary_text}"
    for ch in reply:
        await asyncio.sleep(_MOCK_TOKEN_DELAY)
        yield DeltaEvent(content=ch)
    yield DoneEvent()


# =============================================================================
# Category E — 복합 통합 시나리오 (E1 composite_full_demo)
# =============================================================================
#
# 이 시나리오는 한 사용자 turn 안에서 다음 흐름을 자동 시연한다:
#   orch.add_todo(2) → orch.dispatch(research) → [sub: skill+reason+todo+complete+done]
#   → orch.complete_todo(1) → orch.dispatch(coding) → [sub: skill+reason+todo+complete+done]
#   → orch.complete_todo(2) → orch.reason+delta(최종 보고)
#
# 각 단계는 messages 안의 tool_result prefix 검사로 진입을 결정한다.


def _is_composite_sub_context(messages: list[Message]) -> bool:
    """sub-agent 의 user(task) 메시지에 composite marker 가 포함되어 있는지.

    sub-agent context 의 user 메시지는 항상 sub_messages[1] (task) 이다.
    """
    for m in messages:
        if m.role == "user":
            if _COMPOSITE_TASK_MARKER in m.content:
                return True
            # sub-agent context 의 user 메시지는 단 하나 — 첫 번째에서 결정.
            return False
    return False


async def _composite_orch_scenario(
    messages: list[Message],
) -> AsyncIterator[StreamEvent]:
    """E1 — 오케스트레이터 측 단계 머신."""
    has_add = _has_recent_tool_result(messages, "mock-comp-orch-add-")
    has_dispatch_research = _has_recent_tool_result(
        messages, "mock-comp-orch-dispatch-research-"
    )
    has_dispatch_coding = _has_recent_tool_result(
        messages, "mock-comp-orch-dispatch-coding-"
    )
    completed_count = sum(
        1
        for m in messages
        if m.role == "tool"
        and (m.tool_call_id or "").startswith("mock-comp-orch-complete-")
    )

    # Step 1 — add_todo 로 2단계 계획 등록.
    if not has_add:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"mock-comp-orch-add-{uuid.uuid4().hex[:8]}",
                name="add_todo",
                arguments={
                    "items": [
                        {
                            "description": "리서치 단계 — research_agent 에 위임",
                            "tool_name": "call_sub_agent",
                        },
                        {
                            "description": "코드 검토 단계 — coding_agent 에 위임",
                            "tool_name": "call_sub_agent",
                        },
                    ]
                },
            )
        )
        yield DoneEvent()
        return

    # Step 2 — research_agent 위임.
    if not has_dispatch_research:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"mock-comp-orch-dispatch-research-{uuid.uuid4().hex[:8]}",
                name="call_sub_agent",
                arguments={
                    "agent_name": "research_agent",
                    "task": f"{_COMPOSITE_TASK_MARKER} 데이터 분석 단계 수행",
                },
            )
        )
        yield DoneEvent()
        return

    # 오케스트레이터 todo 의 task_id 두 개 파싱.
    orch_todo_ids = _extract_task_ids(messages, "mock-comp-orch-add-")

    # Step 3 — 첫 번째 todo(리서치) 완료 처리.
    if completed_count == 0 and orch_todo_ids:
        first_id = orch_todo_ids[0]
        yield ToolCallEvent(
            call=ToolCall(
                id=f"mock-comp-orch-complete-{first_id}",
                name="complete_todo",
                arguments={
                    "task_id": first_id,
                    "summary": "research_agent 완료 — 핵심 인사이트 수집",
                },
            )
        )
        yield DoneEvent()
        return

    # Step 4 — coding_agent 위임.
    if not has_dispatch_coding:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"mock-comp-orch-dispatch-coding-{uuid.uuid4().hex[:8]}",
                name="call_sub_agent",
                arguments={
                    "agent_name": "coding_agent",
                    "task": f"{_COMPOSITE_TASK_MARKER} 코드 검토 단계 수행",
                },
            )
        )
        yield DoneEvent()
        return

    # Step 5 — 두 번째 todo(코드 검토) 완료 처리.
    if completed_count == 1 and len(orch_todo_ids) >= 2:
        second_id = orch_todo_ids[1]
        yield ToolCallEvent(
            call=ToolCall(
                id=f"mock-comp-orch-complete-{second_id}",
                name="complete_todo",
                arguments={
                    "task_id": second_id,
                    "summary": "coding_agent 완료 — 이슈 식별 및 권장사항 도출",
                },
            )
        )
        yield DoneEvent()
        return

    # Step 6 — 최종 통합 보고 (reasoning + markdown delta).
    reasoning = (
        "두 서브 에이전트의 보고를 통합합니다. "
        "리서치 결과의 핵심 인사이트와 코드 검토에서 도출된 권장사항을 "
        "사용자가 읽기 쉬운 형태로 정리합니다..."
    )
    for i in range(0, len(reasoning), 6):
        await asyncio.sleep(_MOCK_TOKEN_DELAY)
        yield ReasoningEvent(content=reasoning[i : i + 6])

    reply = (
        "## 종합 시연 결과\n\n"
        "두 서브 에이전트의 작업을 모두 마쳤습니다.\n\n"
        "### 1. 리서치 (research_agent · data_analysis skill)\n"
        "- 데이터 수집 · 정제 · 요약 3단계 완료\n"
        "- 핵심 인사이트 3가지 추출\n\n"
        "### 2. 코드 검토 (coding_agent · code_review skill)\n"
        "- 스캔 · 이슈 식별 · 권장사항 3단계 완료\n"
        "- 이슈 5건, 권장 3건 도출\n\n"
        "전체 분석이 정상적으로 마무리되었습니다."
    )
    for ch in reply:
        await asyncio.sleep(_MOCK_TOKEN_DELAY)
        yield DeltaEvent(content=ch)
    yield DoneEvent()


async def _composite_sub_scenario(
    messages: list[Message], agent_name: str
) -> AsyncIterator[StreamEvent]:
    """E1 — 서브 에이전트 측 단계 머신.

    research_agent → data_analysis skill / coding_agent → code_review skill.
    각자 자체 add_todo 3개 → complete_todo × 3 → complete_subagent.
    """
    skill_name = "data_analysis" if agent_name == "research_agent" else "code_review"

    todo_prefix = f"mock-comp-sub-{agent_name}-todo-"
    complete_prefix = f"mock-comp-sub-{agent_name}-complete-"

    has_todo = _has_recent_tool_result(messages, todo_prefix)

    # Step A — skill 활성화 + reasoning + add_todo (한 iteration 안에 묶음).
    if not has_todo:
        # SkillActiveEvent 는 harness 가 AgentProgressEvent[skill_active] 로 래핑.
        yield SkillActiveEvent(skills=[skill_name])

        if agent_name == "research_agent":
            reasoning = (
                "데이터 분석을 수집 · 정제 · 요약 3단계로 분해하겠습니다. "
                "각 단계를 add_todo 로 등록하고 순차적으로 처리합니다..."
            )
            items = [
                {"description": "데이터 수집"},
                {"description": "정제 (결측·중복 제거)"},
                {"description": "요약 (핵심 인사이트 추출)"},
            ]
        else:
            reasoning = (
                "코드 검토를 스캔 · 이슈 식별 · 권장사항 3단계로 진행합니다. "
                "각 단계를 add_todo 로 등록하고 순차적으로 처리합니다..."
            )
            items = [
                {"description": "코드 스캔"},
                {"description": "이슈 식별"},
                {"description": "권장사항 도출"},
            ]

        for i in range(0, len(reasoning), 6):
            await asyncio.sleep(_MOCK_TOKEN_DELAY)
            yield ReasoningEvent(content=reasoning[i : i + 6])

        yield ToolCallEvent(
            call=ToolCall(
                id=f"{todo_prefix}{uuid.uuid4().hex[:8]}",
                name="add_todo",
                arguments={"items": items},
            )
        )
        yield DoneEvent()
        return

    # sub-state 의 task_id 들을 파싱.
    sub_todo_ids = _extract_task_ids(messages, todo_prefix)
    completed_ids = {
        m.tool_call_id.replace(complete_prefix, "", 1)
        for m in messages
        if m.role == "tool" and (m.tool_call_id or "").startswith(complete_prefix)
    }
    pending_ids = [tid for tid in sub_todo_ids if tid not in completed_ids]

    # Step B — 미완료 todo 한 개씩 순차 완료.
    if pending_ids:
        tid = pending_ids[0]
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{complete_prefix}{tid}",
                name="complete_todo",
                arguments={"task_id": tid, "summary": "단계 완료"},
            )
        )
        yield DoneEvent()
        return

    # Step C — 모든 sub-todo 완료 → reasoning + complete_subagent.
    if agent_name == "research_agent":
        wrap_reason = "수집된 데이터에서 핵심 인사이트 3가지를 정리합니다..."
        wrap_summary = "데이터 분석 3단계 완료 — 수집·정제 후 핵심 인사이트 3가지 추출"
    else:
        wrap_reason = "식별된 이슈를 우선순위에 따라 권장사항으로 정리합니다..."
        wrap_summary = "코드 검토 3단계 완료 — 이슈 5건 식별, 권장 3건 도출"

    for i in range(0, len(wrap_reason), 6):
        await asyncio.sleep(_MOCK_TOKEN_DELAY)
        yield ReasoningEvent(content=wrap_reason[i : i + 6])

    yield ToolCallEvent(
        call=ToolCall(
            id=f"mock-comp-sub-{agent_name}-finish-{uuid.uuid4().hex[:8]}",
            name="complete_subagent",
            arguments={"summary": wrap_summary},
        )
    )
    yield DoneEvent()


# =============================================================================
# 공용 헬퍼
# =============================================================================


def _detect_sub_agent_name(messages: list[Message]) -> str | None:
    """system 메시지에 "당신은 '<name>' 서브 에이전트" 헤더가 있으면 agent_name 추출.

    _compose_sub_agent_system_prompt 가 항상 이 헤더를 포함하므로 오케스트레이터
    컨텍스트와 서브 에이전트 컨텍스트를 결정론적으로 구분할 수 있다.
    """
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
    """대화 히스토리에서 가장 최근 user 메시지를 반환한다."""
    for m in reversed(messages):
        if m.role == "user":
            return m
    return None


def _matches(text: str, triggers: tuple[str, ...]) -> bool:
    """text 에 triggers 중 하나라도 포함되어 있으면 True."""
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


def _extract_task_ids(messages: list[Message], add_todo_prefix: str) -> list[str]:
    """add_todo 의 tool_result content 에서 등록된 task_id 들을 순서대로 추출.

    harness 의 _handle_add_todo 는 결과 텍스트에
    "[planner] added N todo(s): ['id1', 'id2', ...]" 를 기록하므로,
    그 안의 8자 hex 식별자를 정규식으로 뽑아낸다.
    """
    out: list[str] = []
    for m in messages:
        if m.role == "tool" and (m.tool_call_id or "").startswith(add_todo_prefix):
            out.extend(re.findall(r"'([0-9a-f]{8})'", m.content))
    return out


def _compose_reply(last_user: Message | None, messages: list[Message]) -> str:
    """도구 결과 또는 echo 텍스트를 조합해 응답 문자열을 만든다."""
    last = messages[-1] if messages else None
    if last and last.role == "tool":
        call_id = last.tool_call_id or ""
        if call_id.startswith("mock-now-"):
            return f"현재 시각은 {last.content} 입니다."
        if call_id.startswith("mock-todo-"):
            return (
                "보고서 작업 계획을 등록했습니다.\n\n"
                "다음 3단계로 진행됩니다:\n"
                "1. 매출 데이터 조회 (fetch_sales)\n"
                "2. 보고서 본문 생성 (render_report)\n"
                "3. 이메일 발송 (send_email)\n\n"
                "보고 기간을 알려주시면 바로 시작할게요."
            )
        if call_id.startswith("mock-search-"):
            return f"검색이 완료되었습니다. 결과: {last.content}"

    if last_user is None:
        return "안녕하세요. 무엇을 도와드릴까요?"

    return (
        f"[mock] '{last_user.content}' 라고 하셨네요. "
        "실제 LLM 이 연결되면 이 자리에 답변이 옵니다."
    )
