"""공통 system prompt 섹션 렌더러 — 오케스트레이터/단층 경로가 동일하게 재사용.

이전에 두 ``_compose_*`` 함수에 중복돼 있던 카탈로그/멀티스킬/To-do/Pending Slot
블록을 일원화한다. 모두 입력 → ``str | None`` 순수 함수다.
"""

from agent.models import AgentState
from agent.registries.skills import Skill, SkillRegistry


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


def _render_progress_summary_section(state: AgentState) -> str | None:
    """원래 목표 + 롤링 압축 요약 섹션 — 히스토리 트림으로 인한 망각을 보완한다.

    objective(첫 턴 박제)와 progress_summary(summarize-then-drop 누적)가 둘 다 비어
    있으면 섹션을 생략한다. 마지막 줄은 namespace 휘발 대비 load_artifact 복원 너지다.
    """
    if not state.objective and not state.progress_summary:
        return None
    lines: list[str] = ["\n# 이전 진행 요약"]
    if state.objective:
        lines.append(f"원래 목표: {state.objective}")
    if state.progress_summary:
        lines.append(f"지금까지의 진행: {state.progress_summary}")
    lines.append(
        "오래된 대화 일부가 컨텍스트에서 잘렸을 수 있다. 과거 산출물이 필요하면 "
        "아래 # Session Artifacts 의 경로를 load_artifact 로 복원하라."
    )
    return "\n".join(lines)


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
