"""Harness 의 LLM 컨텍스트(system prompt) 조립 로직.

``harness.run_turn`` 이 매 턴 동적으로 합성하는 system prompt 의 모든 텍스트
섹션을 여기에 모은다. 모두 입력 → 문자열의 순수 함수라 turn 실행 루프(harness.py)
와 분리해도 부수효과가 없다.

구성 함수:
    - 오케스트레이터: ``_compose_orchestrator_system_prompt``
    - 서브 에이전트: ``_compose_sub_agent_system_prompt``
    - 단층 fallback(AGENTS 부재): ``_compose_system_prompt``

공통 섹션 렌더러(``_render_*``)는 오케스트레이터와 단층 경로가 동일하게 재사용해
이전에 두 ``compose_*`` 함수에 중복돼 있던 카탈로그/멀티스킬/To-do 블록을 일원화한다.

> 하위호환: harness.py 가 이 모듈의 공개 심볼을 re-export 하므로 기존
> ``from agent.harness import _compose_orchestrator_system_prompt`` 류 import 은
> 그대로 동작한다.
"""

from agent.models import AgentState
from agent.registries.agents import Agent, AgentRegistry
from agent.registries.skills import Skill, SkillRegistry
from agent.runtime import introspect
from core.result_store import current_client_id, read_manifest_entries

# Session Artifacts 프롬프트 섹션 — 노출 개수와 설명 절단 길이 (토큰 예산 통제).
_ARTIFACTS_SECTION_LIMIT = 10
_ARTIFACT_DESC_MAX_CHARS = 80


def _build_wind_down_message(remaining_calls: int) -> str:
    """반복 예산 임박 시 LLM 컨텍스트에 주입할 마무리 지시문을 생성한다 (R7).

    실패 없이 진행 중인데 예산만 소진돼 사용자 노출 단계(display_*)가 hard-cut
    되는 것을 막는다. fallback 메시지와 동일하게 turn-local — 히스토리 비영속.

    Args:
        remaining_calls: 이번 호출을 포함해 남은 provider 호출 수.

    Returns:
        role=user 로 주입할 [System] 지시문.
    """
    if remaining_calls <= 1:
        return (
            "[System] 이번 응답이 이 턴의 마지막 provider 호출입니다. 도구를 호출하지 "
            "말고, 지금까지 완료한 작업과 산출물을 정리한 최종 답변을 작성하세요."
        )
    return (
        f"[System] 이 턴의 반복 예산이 거의 소진되었습니다 (남은 호출 {remaining_calls}회). "
        "새로운 분석·데이터 생성을 시작하지 마세요. 이미 저장된 산출물이 있으면 지금 즉시 "
        "display_chart/display_markdown 등으로 사용자에게 표시하고 complete_todo 로 plan 을 "
        "정리한 뒤, 다음 응답에서 도구 호출 없이 최종 요약을 작성하세요."
    )


# --------------------------------------------------------------------------- #
# 공통 섹션 렌더러 — 오케스트레이터/단층 경로가 동일하게 재사용
# --------------------------------------------------------------------------- #


def _render_inactive_skill_catalog(
    skills: list[Skill], skill_registry: SkillRegistry | None
) -> str | None:
    """비활성 SKILL 카탈로그 — LLM 이 의미 기반으로 activate_skill 을 호출하도록."""
    if skill_registry is None:
        return None
    active_names = {s.meta.name for s in skills}
    inactive_metas = [
        m for m in skill_registry.list_meta() if m.name not in active_names
    ]
    if not inactive_metas:
        return None

    catalog_lines: list[str] = [
        "\n# 가용 SKILL 카탈로그 (비활성)",
        "trigger 키워드가 질의에 없어도 의미가 맞으면 `activate_skill(name=...)` 으로 활성화하라.",
    ]
    for m in inactive_metas:
        trigger_hint = (
            f"  (예시 트리거: {', '.join(m.trigger[:3])})" if m.trigger else ""
        )
        catalog_lines.append(f"- **{m.name}**: {m.description}{trigger_hint}")
    return "\n".join(catalog_lines)


def _render_multi_skill_instruction(skills: list[Skill]) -> str | None:
    """2개 이상 스킬 동시 활성화 시 plan 작성을 강제하는 실행 지침."""
    if len(skills) <= 1:
        return None
    skill_names = ", ".join(f"`{s.meta.name}`" for s in skills)
    return (
        f"\n# 멀티 스킬 실행 지침\n"
        f"현재 {len(skills)}개 스킬이 동시에 활성화되었습니다: {skill_names}.\n"
        f"실제 작업을 시작하기 전에 반드시 `add_todo` 로 각 스킬의 실행 순서와 "
        f"단계를 먼저 등록하세요. 한 스킬의 작업이 완료될 때마다 즉시 "
        f"`complete_todo` 로 표시한 뒤 다음 스킬 작업으로 넘어가세요."
    )


def _render_todo_section(state: AgentState) -> str | None:
    """현재 To-do 목록 섹션."""
    if not state.todo_list:
        return None
    rendered = "\n".join(
        f"- [{t.status.value}] ({t.task_id}) {t.description}" for t in state.todo_list
    )
    return f"\n# 현재 To-do\n{rendered}"


def _render_pending_slot(state: AgentState) -> str | None:
    """미완 도구 슬롯 안내 — 직전 턴 AskUser 응답 재개 유도."""
    if not (state.pending_tool and state.missing_slots):
        return None
    first_q = next(iter(state.missing_slots.values()))
    return (
        "\n# Pending Slot\n"
        f"당신은 직전 턴에 도구 `{state.pending_tool}` 호출을 위해 "
        f"사용자에게 다음을 물었고 응답을 기다리는 중입니다: '{first_q}'.\n"
        f"부분적으로 채워진 인자: {state.pending_args}.\n"
        "사용자의 이번 메시지가 그 질문에 대한 응답이면 같은 도구를 채워서 다시 호출하세요. "
        "새 주제로 전환된 메시지라면 이 pending 호출을 폐기하고 새 요청을 처리하세요."
    )


def _render_session_artifacts_section(limit: int = _ARTIFACTS_SECTION_LIMIT) -> str:
    """현재 세션 산출물 목록을 '# Session Artifacts' 프롬프트 섹션으로 렌더링한다.

    히스토리 윈도우 밖이나 세션 복원(tool 메시지 소실) 후에도 LLM 이 과거
    산출물을 재발견할 수 있도록, 디스크 manifest 를 진실원천으로 최근 N개를
    compact 하게 노출한다. 빈 세션이면 빈 문자열을 반환해 섹션을 생략한다.

    Args:
        limit: 노출할 최대 산출물 수.

    Returns:
        '# Session Artifacts' 섹션 문자열, 또는 산출물이 없으면 "".
    """
    client_id = current_client_id()
    if not client_id:
        return ""

    entries = read_manifest_entries(client_id, limit)
    if not entries:
        return ""

    lines: list[str] = [
        "\n# Session Artifacts",
        "이 세션에서 저장된 산출물 (최신순). 사용자가 과거 산출물을 지칭하면 아래 경로를 사용하라:",
    ]
    for e in entries:
        path = e.get("path", "")
        if not path:
            continue
        kind = e.get("kind", "")
        desc = str(e.get("description", "")).strip()[:_ARTIFACT_DESC_MAX_CHARS]
        shape = ""
        if e.get("rows") is not None and e.get("columns") is not None:
            shape = f", {e['rows']}×{e['columns']}"
        suffix = f" — {desc}" if desc else ""
        lines.append(f"- {path} ({kind}{shape}){suffix}")

    lines.append(
        "재표시는 display_markdown/display_chart/display_image 에 경로를 직접 전달하고, "
        "재계산·추가분석은 load_artifact(path=..., store_as=...) 로 namespace 에 로드하라. "
        "전체 목록이 필요하면 list_artifacts 를 호출하라. "
        "exec_code 에서 'result/...' 를 open() 으로 직접 열지 말고 load_artifact 를 쓰라 "
        "(frozen EXE 경로 안전)."
    )
    return "\n".join(lines)


def _render_skills_api_refs(skills: list[Skill]) -> str:
    """활성 SKILL 목록의 api_refs 를 평면화해 ApiDoc 섹션으로 렌더링한다.

    중복 ref 는 한 번만 노출하고, 모두 비어 있으면 빈 문자열 반환.
    """
    refs: list[str] = []
    seen: set[str] = set()
    for s in skills:
        for r in s.meta.api_refs:
            if r not in seen:
                refs.append(r)
                seen.add(r)
    if not refs:
        return ""
    docs = introspect.collect_api_docs(refs)
    return introspect.render_api_docs_section(docs)


def _collect_agent_api_refs_section(agent: Agent, skill_bodies: list[Skill]) -> str:
    """에이전트 + 학습 SKILL 들의 api_refs 를 평면화해 ApiDoc 섹션 텍스트로 반환."""
    refs: list[str] = []
    seen: set[str] = set()
    for r in agent.meta.api_refs:
        if r not in seen:
            refs.append(r)
            seen.add(r)
    for s in skill_bodies:
        for r in s.meta.api_refs:
            if r not in seen:
                refs.append(r)
                seen.add(r)
    if not refs:
        return ""
    docs = introspect.collect_api_docs(refs)
    return introspect.render_api_docs_section(docs)


# --------------------------------------------------------------------------- #
# 계층형(오케스트레이터 + 서브 에이전트) system prompt
# --------------------------------------------------------------------------- #


def _compose_orchestrator_system_prompt(
    *,
    base: str,
    skills: list[Skill],
    state: AgentState,
    agent_registry: AgentRegistry,
    skill_registry: SkillRegistry | None = None,
) -> str:
    """오케스트레이터 system prompt — 기존 조립 + 가용 에이전트 카탈로그 동적 주입."""
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

    # Library runtime — 활성 스킬들의 api_refs 를 모아 한 섹션으로 주입.
    api_section = _render_skills_api_refs(skills)
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


# --------------------------------------------------------------------------- #
# 단층 fallback (하위호환) — AGENTS 가 없을 때
# --------------------------------------------------------------------------- #


def _compose_system_prompt(
    base: str,
    skills: list[Skill],
    state: AgentState,
    skill_registry: SkillRegistry | None = None,
) -> str:
    """PROMPTS 베이스 + 선택된 SKILLS 본문 + AgentState 요약을 합성한다 (단층).

    오케스트레이터 카탈로그 / Case 3 매핑 없이 기존 동작 그대로. agent_registry 가
    None 일 때만 사용 — 하위호환을 위해 보존.
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

    return "\n".join(parts)
