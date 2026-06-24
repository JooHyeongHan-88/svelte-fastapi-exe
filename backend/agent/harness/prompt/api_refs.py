"""api_refs → ApiDoc 섹션 렌더링.

활성 SKILL·서브 에이전트의 ``api_refs`` 목록을 평면화(중복 제거)해 introspect 가
생성하는 ApiDoc 섹션 텍스트로 변환한다. Library runtime 노출 패턴(B)의 프롬프트 측.
"""

from agent.registries.agents import Agent
from agent.registries.skills import Skill
from agent.runtime import introspect


def _render_skills_api_refs(
    skills: list[Skill], extra_refs: list[str] | None = None
) -> str:
    """활성 SKILL 목록(+ extra_refs)의 api_refs 를 평면화해 ApiDoc 섹션으로 렌더링한다.

    중복 ref 는 한 번만 노출하고, 모두 비어 있으면 빈 문자열 반환.
    extra_refs 는 오케스트레이터 baseline api_refs(APP_ORCHESTRATOR_API_REFS) 용 —
    활성 SKILL 이 없거나 api_refs 가 없어도 상시 노출하고 싶은 dotted-path 들이다.
    SKILL refs 뒤에 이어 붙여 dedup 한다.
    """
    refs: list[str] = []
    seen: set[str] = set()
    for s in skills:
        for r in s.meta.api_refs:
            if r not in seen:
                refs.append(r)
                seen.add(r)
    for r in extra_refs or []:
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
