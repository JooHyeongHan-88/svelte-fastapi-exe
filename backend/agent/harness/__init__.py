"""Agent harness 서브시스템 — provider ↔ 도구 turn 실행 루프.

run_turn 한 번 = 사용자 입력 1건에 대한 응답 1턴. 계층형 멀티 에이전트
(오케스트레이터 + 서브 에이전트) 실행을 담당한다.

구성:
    - core: run_turn 진입점 + provider→tool 루프 + 서브에이전트 dispatch + 도구 실행.
    - prompts: LLM system prompt 동적 조립 (오케스트레이터 / 서브에이전트 / 단층 fallback).
    - state: AgentState 변형(todo)·대화 히스토리 정합성(tool 쌍 보존)·루프 가드 시그니처.

공개 API 는 backend/api/chat.py 가 ``from agent.harness import run_turn`` 으로 사용한다.
core 가 prompts·state 의 심볼을 이미 re-export 하므로, 하위호환을 위해 내부 헬퍼도
이 패키지 네임스페이스에서 그대로 접근 가능하게 한곳(core)에서 끌어와 노출한다.
"""

from agent.harness.core import (  # noqa: F401  (re-export — 하위호환)
    ORCHESTRATOR_ID,
    TurnBudget,
    _ERROR_TOOL_PLACEHOLDER,
    _balance_all_unresolved,
    _balance_unresolved_tool_calls,
    _call_signature,
    _compose_orchestrator_system_prompt,
    _compose_sub_agent_system_prompt,
    _dispatch_parallel_sub_agents,
    _dispatch_sub_agent,
    _execute_tool,
    _filter_specs_for_sub_agent,
    _inject_runtime_tools,
    _record_invalid_call,
    _render_session_artifacts_section,
    _run_agent_turn,
    run_turn,
)

__all__ = ["run_turn", "TurnBudget", "ORCHESTRATOR_ID"]
