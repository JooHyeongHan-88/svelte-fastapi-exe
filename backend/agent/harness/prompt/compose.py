"""계층형(오케스트레이터 + 서브 에이전트) / 단층 system prompt 최종 조립.

공통 섹션 렌더러(``sections``·``artifacts``·``api_refs``)를 조합해 세 가지 경로의
system prompt 를 만든다:

- 오케스트레이터: ``_compose_orchestrator_system_prompt``
- 서브 에이전트: ``_compose_sub_agent_system_prompt``
- 단층 fallback(AGENTS 부재): ``_compose_system_prompt``
"""

from agent.models import AgentState
from agent.registries.agents import Agent, AgentRegistry
from agent.registries.skills import Skill, SkillRegistry

from agent.harness.prompt.api_refs import (
    _collect_agent_api_refs_section,
    _render_skills_api_refs,
)
from agent.harness.prompt.artifacts import _render_session_artifacts_section
from agent.harness.prompt.sections import (
    _render_inactive_skill_catalog,
    _render_multi_skill_instruction,
    _render_pending_slot,
    _render_todo_section,
)


def _compose_orchestrator_system_prompt(
    *,
    base: str,
    skills: list[Skill],
    state: AgentState,
    agent_registry: AgentRegistry,
    skill_registry: SkillRegistry | None = None,
    baseline_api_refs: list[str] | None = None,
) -> str:
    """오케스트레이터 system prompt — 기존 조립 + 가용 에이전트 카탈로그 동적 주입.

    baseline_api_refs: APP_ORCHESTRATOR_API_REFS — 활성 SKILL 의 api_refs 와 합쳐
    'Available Library APIs' 섹션에 상시 노출한다(SKILL 없이도 라이브러리 사용 가능).
    """
    parts: list[str] = [base] if base else []

    for s in skills:
        parts.append(f"\n# Skill: {s.meta.name}\n{s.body}")

    catalog = _render_inactive_skill_catalog(skills, skill_registry)
    if catalog:
        parts.append(catalog)

    multi_skill = _render_multi_skill_instruction(skills)
    if multi_skill:
        parts.append(multi_skill)

    todo_section = _render_todo_section(state)
    if todo_section:
        parts.append(todo_section)

    artifacts_section = _render_session_artifacts_section()
    if artifacts_section:
        parts.append(artifacts_section)

    # 서브 에이전트 pending 이 오케스트레이터 자체 pending 보다 우선.
    pending_slot = _render_pending_slot(state)
    if state.pending_sub_agent and state.missing_slots:
        first_q = next(iter(state.missing_slots.values()))
        parts.append(
            "\n# Pending Sub-Agent Slot\n"
            f"직전 턴에 `{state.pending_sub_agent}` 서브 에이전트가 작업 중 "
            f"필요한 정보를 사용자에게 질문했습니다: '{first_q}'.\n"
            f"원래 위임 task: '{state.pending_sub_task}'.\n"
            "사용자의 이번 메시지가 그 응답이라면 즉시 `call_sub_agent` 로 해당 에이전트에게 "
            "사용자가 제공한 정보를 포함해 재위임하세요. "
            "새 주제 전환이면 이 pending 상태를 무시하고 새 요청을 처리하세요."
        )
    elif pending_slot:
        parts.append(pending_slot)
    elif state.pending_question:
        # ask_user sentinel 로 능동 질문을 던진 직후 — 사용자의 이번 메시지가 그 답변이다.
        parts.append(
            "\n# Pending User Question\n"
            f"당신은 직전 턴에 사용자에게 다음을 질문했습니다: '{state.pending_question}'.\n"
            "이번 메시지가 그 질문에 대한 답변이라고 가정하고, 받은 답변을 활용해 작업을 이어가세요. "
            "답변이 여전히 모호하면 다시 `ask_user` 를 호출해도 되지만 같은 질문 반복은 금지합니다 — "
            "그 경우엔 가장 합리적인 해석으로 진행하고 결과 보고에서 그 가정을 명시하세요."
        )

    metas = agent_registry.list_meta()
    if metas:
        catalog_lines: list[str] = ["\n# 가용 서브 에이전트 카탈로그"]
        skill_to_agent: dict[str, str] = {}
        for m in metas:
            skills_str = ", ".join(m.skills) if m.skills else "(없음)"
            agent_block: list[str] = [f"- **{m.name}**: {m.description}"]
            if m.role:
                agent_block.append(f"  Role: {m.role}")
            if m.goal:
                agent_block.append(f"  Goal: {m.goal}")
            if m.when_to_delegate:
                # YAML | 블록 입력에 포함된 줄바꿈은 시각적 노이즈가 되므로 한 줄로 정규화.
                inlined = " ".join(m.when_to_delegate.split())
                agent_block.append(f"  When to delegate: {inlined}")
            agent_block.append(f"  전담 스킬: {skills_str}")
            catalog_lines.append("\n".join(agent_block))
            for sk in m.skills:
                skill_to_agent.setdefault(sk, m.name)

        if skill_to_agent:
            mapping_lines = [
                f"- '{sk}' 트리거가 들어오면 반드시 `{ag}` 에게 `call_sub_agent` 로 위임"
                for sk, ag in skill_to_agent.items()
            ]
            catalog_lines.append(
                "\n## Case 3 결정론 매핑 (반드시 준수)\n" + "\n".join(mapping_lines)
            )
        parts.append("\n".join(catalog_lines))

    # Library runtime — 활성 스킬들의 api_refs + 오케스트레이터 baseline 을 한 섹션으로 주입.
    api_section = _render_skills_api_refs(skills, extra_refs=baseline_api_refs)
    if api_section:
        parts.append("\n" + api_section)

    return "\n".join(parts)


def _compose_sub_agent_system_prompt(
    *,
    base: str,
    agent: Agent,
    skill_bodies: list[Skill],
) -> str:
    """서브 에이전트 system prompt — 격리된 컨텍스트로 페르소나·스킬 본문 주입.

    구성: safety+base (orchestrator.md 제외) + 에이전트 본문 + 학습 SKILL 본문
    + Library APIs (있으면) + Task Summary 종료 규약. 'call_sub_agent' 도구는
    spec 에서 제거되므로 LLM 시야에 보이지 않는다 (무한 재귀 방지).
    """
    parts: list[str] = [base] if base else []
    identity_lines: list[str] = [f"\n# 당신은 '{agent.meta.name}' 서브 에이전트입니다"]
    if agent.meta.role:
        identity_lines.append(f"- Role: {agent.meta.role}")
    if agent.meta.goal:
        identity_lines.append(f"- Goal: {agent.meta.goal}")
    if len(identity_lines) > 1:
        # role/goal 블록과 body 사이 시각 구분을 위한 빈 줄.
        identity_lines.append("")
    identity_lines.append(agent.body)
    parts.append("\n".join(identity_lines))
    for s in skill_bodies:
        parts.append(f"\n# 학습 Skill: {s.meta.name}\n{s.body}")

    # 에이전트 자체 api_refs + 학습 SKILL 들의 api_refs 를 합쳐 API 섹션으로 주입.
    api_section = _collect_agent_api_refs_section(agent, skill_bodies)
    if api_section:
        parts.append("\n" + api_section)

    parts.append(
        "\n# 종료 규약 (필수)\n"
        "작업을 완료했으면 반드시 `complete_subagent` 도구를 호출해 결과를 반환하라.\n"
        "summary 파라미터에 수행한 내용과 핵심 결과를 1~3문장으로 기술한다.\n"
        "`complete_subagent` 를 호출하지 않으면 오케스트레이터가 결과를 인식하지 못하므로 "
        "작업 완료 시 마지막 액션으로 반드시 호출해야 한다."
    )
    return "\n".join(parts)


def _compose_system_prompt(
    base: str,
    skills: list[Skill],
    state: AgentState,
    skill_registry: SkillRegistry | None = None,
    baseline_api_refs: list[str] | None = None,
) -> str:
    """PROMPTS 베이스 + 선택된 SKILLS 본문 + AgentState 요약을 합성한다 (단층).

    오케스트레이터 카탈로그 / Case 3 매핑 없이 기존 동작 그대로. agent_registry 가
    None 일 때만 사용 — 하위호환을 위해 보존.

    baseline_api_refs: APP_ORCHESTRATOR_API_REFS — 단층 모드에서도 런타임 도구 주입
    (공유 경로)과 프롬프트 문서를 일치시키기 위해 baseline 이 있으면 API 섹션을 붙인다.
    """
    parts: list[str] = [base] if base else []

    for s in skills:
        parts.append(f"\n# Skill: {s.meta.name}\n{s.body}")

    catalog = _render_inactive_skill_catalog(skills, skill_registry)
    if catalog:
        parts.append(catalog)

    multi_skill = _render_multi_skill_instruction(skills)
    if multi_skill:
        parts.append(multi_skill)

    todo_section = _render_todo_section(state)
    if todo_section:
        parts.append(todo_section)

    artifacts_section = _render_session_artifacts_section()
    if artifacts_section:
        parts.append(artifacts_section)

    pending_slot = _render_pending_slot(state)
    if pending_slot:
        parts.append(pending_slot)

    # 단층 모드는 기존엔 api_refs 섹션을 렌더하지 않았다. baseline 이 지정된 경우에만
    # 추가해 도구 주입과 문서를 일관시킨다(빈 baseline 이면 기존 동작 그대로).
    if baseline_api_refs:
        api_section = _render_skills_api_refs(skills, extra_refs=baseline_api_refs)
        if api_section:
            parts.append("\n" + api_section)

    return "\n".join(parts)
