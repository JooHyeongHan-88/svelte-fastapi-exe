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
        검증: SkillBadge(time_check) · now → display_image → save_artifact +
              display_markdown → 자연어 응답 (Artifact 패널 image+markdown 탭)

    D. data_summary via analyst_agent (Case 3 단일 위임)
                                     trigger="데이터 요약", "요약 통계"
        검증: SkillBadge(data_summary) · AgentSwitch/Return · AgentProgress 래핑
              · sub 안 ReasoningBlock / TodoProgress(3) / SkillCompleteBadge
              · exec_code + call_function + eval_expression 3종 메타 도구
              · display_chart(bar) · 오케스트레이터 최종 보고

    E. composite — analyst → writer  trigger="전체 분석 보고서", "종합 보고서"
        검증: 오케스트레이터 multi-step plan(2) · AgentTrail 칩 2개
              · analyst sub: exec_code + call_function + display_chart + TodoProgress(2)
              · writer sub: save_artifact + display_markdown
              · 최종 ReasoningEvent + markdown 통합 보고

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
import logging
import re
import shutil
import uuid
from collections.abc import AsyncIterator

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
from core.config import WEB_DIR
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
_C_IMG_PREFIX = "mock-C-img-"
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
    """4 턴 흐름: now → display_image → save_artifact+display_markdown → 자연어 응답."""
    has_now = _has_recent_tool_result(messages, _C_NOW_PREFIX)
    has_img = _has_recent_tool_result(messages, _C_IMG_PREFIX)
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

    # 턴 2: 시계 테마 이미지 표시.
    if not has_img:
        favicon_path = _ensure_favicon_artifact()
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_C_IMG_PREFIX}{uuid.uuid4().hex[:8]}",
                name="display_image",
                arguments={
                    "source": favicon_path,
                    "alt": "시간 확인 데모 이미지",
                    "caption": "현재 시각 확인 작업의 시각화 자료",
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 3: save_artifact + display_markdown 동시.
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

    # 턴 4: 자연어 최종 응답.
    now_text = _latest_tool_content(messages, _C_NOW_PREFIX) or "(알 수 없음)"
    reply = (
        f"현재 시각은 **{now_text}** 입니다.\n\n"
        "우측 패널에 시각 자료(이미지)와 시각 기록(마크다운) 산출물이 함께 표시되었습니다."
    )
    for ch in reply:
        await asyncio.sleep(_MOCK_TOKEN_DELAY)
        yield DeltaEvent(content=ch)
    yield DoneEvent()


def _ensure_favicon_artifact() -> str:
    """favicon.svg 를 현재 턴 슬롯에 복사하고 display_image source 상대경로를 반환한다.

    원본이 없으면 build 결과 경로를 직접 사용한다.
    """
    source_path = WEB_DIR / "assets" / "favicon.svg"
    if not source_path.exists():
        logger.debug("favicon source not found at %s — using build path", source_path)
        return "build/web/assets/favicon.svg"

    slot = artifact_slot()
    dest = slot / "favicon.svg"
    shutil.copy2(source_path, dest)
    return f"result/{session_dir_name()}/{slot.name}/{dest.name}"


def _current_turn_slot_name() -> str:
    """현재 턴 슬롯의 폴더명(YYYYMMDD-HHmmss). save_artifact 가 사용할 폴더와 일치."""
    slot = artifact_slot()
    return slot.name


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
_D_SUB_EXEC_PREFIX = "mock-D-sub-exec-"
_D_SUB_CALL_PREFIX = "mock-D-sub-call-"
_D_SUB_EVAL_PREFIX = "mock-D-sub-eval-"
_D_SUB_CHART_PREFIX = "mock-D-sub-chart-"
_D_SUB_COMPLETE_PREFIX = "mock-D-sub-complete-"
_D_SUB_FINISH_PREFIX = "mock-D-sub-finish-"


async def _scenario_D_analyst_sub(
    messages: list[Message],
) -> AsyncIterator[StreamEvent]:
    """analyst_agent sub-context (D 단일 위임).

    턴 1: ReasoningEvent + add_todo(3)
    턴 2: exec_code (samples 정의) + complete_todo(1)
    턴 3: call_function (통계 계산) + complete_todo(2)
    턴 4: eval_expression (mean 추출) + display_chart + complete_todo(3)
    턴 5: complete_subagent
    """
    has_add = _has_recent_tool_result(messages, _D_SUB_ADD_PREFIX)
    has_exec = _has_recent_tool_result(messages, _D_SUB_EXEC_PREFIX)
    has_call = _has_recent_tool_result(messages, _D_SUB_CALL_PREFIX)
    has_chart = _has_recent_tool_result(messages, _D_SUB_CHART_PREFIX)
    task_ids = _extract_task_ids(messages, _D_SUB_ADD_PREFIX)
    completed = _count_completes(messages, _D_SUB_COMPLETE_PREFIX)

    # 턴 1: ReasoningEvent + add_todo(3).
    if not has_add:
        reasoning = (
            "데이터 요약 통계를 계산하기 위해 작업을 3단계로 분해합니다. "
            "샘플 데이터 생성 → compute_summary_stats 호출 → 차트 시각화 순서로 진행합니다..."
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
                        {"description": "샘플 데이터 30건 생성 (samples)"},
                        {"description": "compute_summary_stats 호출 (stats)"},
                        {"description": "차트 시각화 및 단일 지표 추출"},
                    ]
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 2: exec_code → samples 정의 + complete_todo(1).
    if not has_exec and task_ids:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_D_SUB_EXEC_PREFIX}{uuid.uuid4().hex[:8]}",
                name="exec_code",
                arguments={
                    "code": (
                        "# 가상 표본 — y ≈ 0.5x + 노이즈 패턴의 1차원 측정치\n"
                        "samples = [round(i * 0.5 + ((i * 7) % 11 - 5) * 0.4, 3) "
                        "for i in range(30)]\n"
                        "print(f'samples 길이: {len(samples)}, 첫 3개: {samples[:3]}')"
                    )
                },
            )
        )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_D_SUB_COMPLETE_PREFIX}1-{task_ids[0]}",
                name="complete_todo",
                arguments={
                    "task_id": task_ids[0],
                    "summary": "samples 30건 생성 완료",
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 3: call_function → compute_summary_stats + complete_todo(2).
    if not has_call and len(task_ids) >= 2:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_D_SUB_CALL_PREFIX}{uuid.uuid4().hex[:8]}",
                name="call_function",
                arguments={
                    "qualified_name": "scripts.stats.compute_summary_stats",
                    "kwargs": {"data": "$samples"},
                    "store_as": "stats",
                },
            )
        )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_D_SUB_COMPLETE_PREFIX}2-{task_ids[1]}",
                name="complete_todo",
                arguments={
                    "task_id": task_ids[1],
                    "summary": "compute_summary_stats 호출 완료 — stats 변수 저장",
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 4: eval_expression + display_chart + complete_todo(3).
    if not has_chart and len(task_ids) >= 3:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_D_SUB_EVAL_PREFIX}{uuid.uuid4().hex[:8]}",
                name="eval_expression",
                arguments={
                    "expression": "stats['mean']",
                    "store_as": "avg",
                },
            )
        )
        # 차트 series 는 stats 의 일반화된 지표 라벨만 — 구체 값은 namespace 에서 조회.
        # Mock 은 실제 값을 알지 못하므로 placeholder 형태로만 yield 하지 않고,
        # 6개 지표 라벨을 갖는 막대 차트 구조만 전달한다. Harness 가 실제 stats 변수를
        # series 에 주입하는 패턴이 아니므로 mock 은 데모용 더미 값을 사용한다.
        # (실제 LLM 은 tool_result 에서 stats 값을 보고 series 를 구성한다)
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_D_SUB_CHART_PREFIX}{uuid.uuid4().hex[:8]}",
                name="display_chart",
                arguments={
                    "chart_type": "bar",
                    "title": "요약 통계량 (samples)",
                    "x_label": "지표",
                    "y_label": "값",
                    "series": [
                        {
                            "name": "stats",
                            "data": [
                                ["count", 30],
                                ["mean", 7.5],
                                ["median", 7.3],
                                ["stdev", 4.6],
                                ["min", -1.6],
                                ["max", 16.1],
                            ],
                        }
                    ],
                },
            )
        )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_D_SUB_COMPLETE_PREFIX}3-{task_ids[2]}",
                name="complete_todo",
                arguments={
                    "task_id": task_ids[2],
                    "summary": "차트 시각화 및 평균 지표 추출 완료",
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 5: complete_subagent — 모든 단계 완료 시.
    if completed >= 3:
        summary = (
            "Task Summary:\n"
            "- samples 30건에 대해 compute_summary_stats 호출, 6개 지표 산출\n"
            "- 평균 지표(avg)는 별도 추출, 막대 차트 시각화 완료"
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

    1: add_todo(2)
    2: dispatch analyst_agent
    3: complete_todo(1)
    4: dispatch writer_agent (analyst summary embed)
    5: complete_todo(2)
    6: ReasoningEvent + 최종 markdown 응답
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

    # 턴 1: add_todo(2).
    if not has_add:
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
_E_ANALYST_EXEC_PREFIX = "mock-E-analyst-exec-"
_E_ANALYST_CALL_PREFIX = "mock-E-analyst-call-"
_E_ANALYST_CHART_PREFIX = "mock-E-analyst-chart-"
_E_ANALYST_COMPLETE_PREFIX = "mock-E-analyst-complete-"
_E_ANALYST_FINISH_PREFIX = "mock-E-analyst-finish-"


async def _scenario_E_analyst_sub(
    messages: list[Message],
) -> AsyncIterator[StreamEvent]:
    """E analyst sub — D 보다 축약 (add_todo(2) → exec+call → chart → finish)."""
    has_add = _has_recent_tool_result(messages, _E_ANALYST_ADD_PREFIX)
    has_call = _has_recent_tool_result(messages, _E_ANALYST_CALL_PREFIX)
    has_chart = _has_recent_tool_result(messages, _E_ANALYST_CHART_PREFIX)
    task_ids = _extract_task_ids(messages, _E_ANALYST_ADD_PREFIX)
    completed = _count_completes(messages, _E_ANALYST_COMPLETE_PREFIX)

    # 턴 1: add_todo(2).
    if not has_add:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_E_ANALYST_ADD_PREFIX}{uuid.uuid4().hex[:8]}",
                name="add_todo",
                arguments={
                    "items": [
                        {"description": "샘플 데이터 생성 및 통계 계산"},
                        {"description": "차트 시각화"},
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
                id=f"{_E_ANALYST_EXEC_PREFIX}{uuid.uuid4().hex[:8]}",
                name="exec_code",
                arguments={
                    "code": (
                        "samples = [round(i * 0.7 + ((i * 5) % 9 - 4) * 0.3, 3) "
                        "for i in range(24)]\n"
                        "print(f'준비 완료: 표본 {len(samples)}건')"
                    )
                },
            )
        )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_E_ANALYST_CALL_PREFIX}{uuid.uuid4().hex[:8]}",
                name="call_function",
                arguments={
                    "qualified_name": "scripts.stats.compute_summary_stats",
                    "kwargs": {"data": "$samples"},
                    "store_as": "stats",
                },
            )
        )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_E_ANALYST_COMPLETE_PREFIX}1-{task_ids[0]}",
                name="complete_todo",
                arguments={
                    "task_id": task_ids[0],
                    "summary": "샘플 데이터 24건 + compute_summary_stats 호출 완료",
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 3: display_chart + complete_todo(2).
    if not has_chart and len(task_ids) >= 2:
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_E_ANALYST_CHART_PREFIX}{uuid.uuid4().hex[:8]}",
                name="display_chart",
                arguments={
                    "chart_type": "bar",
                    "title": "요약 통계량 (composite 시나리오)",
                    "x_label": "지표",
                    "y_label": "값",
                    "series": [
                        {
                            "name": "stats",
                            "data": [
                                ["count", 24],
                                ["mean", 8.1],
                                ["median", 7.9],
                                ["stdev", 5.2],
                                ["min", -1.2],
                                ["max", 17.4],
                            ],
                        }
                    ],
                },
            )
        )
        yield ToolCallEvent(
            call=ToolCall(
                id=f"{_E_ANALYST_COMPLETE_PREFIX}2-{task_ids[1]}",
                name="complete_todo",
                arguments={
                    "task_id": task_ids[1],
                    "summary": "막대 차트 시각화 완료",
                },
            )
        )
        yield DoneEvent()
        return

    # 턴 4: complete_subagent.
    if completed >= 2:
        summary = (
            "Task Summary:\n"
            "- 표본 24건의 요약 통계 계산 (compute_summary_stats)\n"
            "- 6개 지표 막대 차트 시각화 완료"
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
    """E writer sub — save_artifact + display_markdown 동시 → complete_subagent."""
    has_save = _has_recent_tool_result(messages, _E_WRITER_SAVE_PREFIX)

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

    summary = (
        "Task Summary:\n"
        "- report.md 생성 (요약·핵심 지표 표·인사이트 3건·후속 액션·인용)\n"
        "- ArtifactMarkdown 으로 사이드 패널에 렌더링 완료"
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


def _compose_reply(last_user: Message | None) -> str:
    """A echo 폴백 응답."""
    if last_user is None:
        return "안녕하세요. 무엇을 도와드릴까요?"
    return (
        f"[mock] '{last_user.content}' 라고 하셨네요. "
        "실제 LLM 이 연결되면 이 자리에 답변이 옵니다."
    )
