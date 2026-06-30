"""AgentState pending 슬롯 클리어 — 턴 경계 잔재 정리 (F11).

``run_turn`` 의 성공/예외 경로와 ``call_handlers`` 의 일반 도구 경로가 각각
같은 pending 필드 묶음을 비우던 것을 한 곳으로 모은다. 어느 모듈도 서로를
import 하지 않으므로(state/ 는 loop·call_handlers 를 모름) 순환 없이 공유된다.
"""

from agent.models import AgentState


def has_pending(state: AgentState) -> bool:
    """직전 턴에서 넘어온 미해결 pending 이 하나라도 있는지.

    ask_user(슬롯 가드·sentinel)·서브에이전트 슬롯으로 턴이 끊겼던 작업이 이번 턴에
    재개되는 신호다. SKILL 캐리(loop.py)가 이 동안에만 직전 SKILL 본문을 다시 들고
    간다 — 영구 sticky 가 아니라 pending 해소 시 자동 종료(R5/F11 공격적 클리어 철학 유지).
    ``clear_all_pending`` 과 동일한 필드 묶음을 본다(SSOT).
    """
    return bool(
        state.pending_tool
        or state.missing_slots
        or state.pending_question
        or state.pending_sub_agent
    )


def clear_pending_tool(state: AgentState) -> None:
    """일반 도구의 슬롯 재질문 잔재(pending_tool/args/missing_slots)를 비운다.

    슬롯 누락으로 보류됐던 도구가 같은 턴에 실행·중복차단되면, 다음 턴
    system prompt 가 stale pending 으로 오염되지 않도록 즉시 클리어한다.
    """
    state.pending_tool = None
    state.pending_args = {}
    state.missing_slots = {}


def clear_all_pending(state: AgentState) -> None:
    """tool + sub-agent pending 잔재를 전부 비운다 (F11).

    AskUser 없이 턴이 완료됐거나 예외로 끊겼다 = 사용자 입력 없이 해결됐다 =
    어떤 pending 도 다음 턴으로 넘길 필요가 없다.
    """
    clear_pending_tool(state)
    state.pending_sub_agent = None
    state.pending_sub_task = None
