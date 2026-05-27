"""Sub-agent 위임 · 종료 sentinel 도구.

call_sub_agent  — 오케스트레이터가 서브 에이전트에게 작업을 위임한다.
complete_subagent — 서브 에이전트가 작업을 마쳤을 때 결과를 오케스트레이터에 반환한다.

두 도구 모두 harness 가 tool_call 단계에서 직접 처리하므로 함수 본문은 실행되지 않는다.
"""

from typing import Annotated

from agent.registries.tools import (
    COMPLETE_SUB_AGENT,
    SUB_AGENT_DISPATCH,
    register_tool,
)


@register_tool(
    name=SUB_AGENT_DISPATCH,
    description=(
        "특정 서브 에이전트에게 작업을 위임한다. "
        "When to use: 작업이 다단계이고 카탈로그에 명시된 도메인 전문성(when_to_delegate)이 매칭될 때, "
        "또는 사용자가 명시적으로 에이전트를 지목했을 때. "
        "When NOT to use: 단순 도구 1~2회로 끝나는 작업(직접 실행이 더 효율적), "
        "또는 같은 에이전트를 3회 연속 호출(loop-guard 가 차단), "
        "또는 자신이 이미 서브 에이전트일 때(서브가 서브를 부르는 행위는 금지). "
        "agent_name 은 가용 서브 에이전트 카탈로그에 등록된 에이전트 식별자, "
        "task 는 그 에이전트가 수행할 한국어 작업 지시문 한 단락이다. "
        "호출 즉시 서브 에이전트 turn 이 자동 실행되고 결과 요약본이 tool_result 로 반환된다."
    ),
    slot_prompts={
        "agent_name": "어느 서브 에이전트에게 작업을 맡길까요?",
        "task": "에이전트가 수행할 작업을 한 문단으로 알려 주세요.",
    },
    sentinel=True,
)
async def call_sub_agent(
    agent_name: Annotated[str, "위임할 서브 에이전트 식별자 (예: coding_agent)"],
    task: Annotated[str, "에이전트가 수행할 작업 지시문 (한국어 한 단락)"],
) -> str:
    raise RuntimeError("sentinel tool — handled by harness, never executed")


@register_tool(
    name=COMPLETE_SUB_AGENT,
    description=(
        "서브 에이전트가 맡은 작업을 완료했을 때 호출한다. "
        "When to use: 서브 에이전트 본인이 모든 step 을 끝낸 직후 마지막 액션으로 한 번만. "
        "When NOT to use: 아직 작업이 끝나지 않았을 때, 또는 오케스트레이터(직접 작업 수행 중)일 때. "
        "summary 에 수행 결과와 핵심 발견 사항을 1~3문장으로 기술한다. "
        "이 도구를 호출해야만 오케스트레이터가 결과를 인식하므로 작업 완료 시 반드시 마지막으로 호출해야 한다."
    ),
    slot_prompts={
        "summary": "수행한 작업과 결과를 1~3문장으로 요약해 주세요.",
    },
    sentinel=True,
)
async def complete_subagent(
    summary: Annotated[
        str, "수행한 작업 결과 요약 (오케스트레이터에 tool_result 로 전달됨)"
    ],
) -> str:
    raise RuntimeError("sentinel tool — handled by harness, never executed")
