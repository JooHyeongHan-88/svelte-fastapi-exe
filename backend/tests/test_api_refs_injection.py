"""SkillMeta/AgentMeta api_refs 필드 + harness 자동 주입 회귀 테스트.

검증 대상:
    1. SkillMeta/AgentMeta 가 api_refs 필드를 파싱한다 (기본값 빈 리스트).
    2. _compose_orchestrator_system_prompt: api_refs 가 있는 SKILL 활성 시
       'Available Library APIs' 섹션이 결과 텍스트에 포함된다.
    3. _compose_sub_agent_system_prompt: 에이전트/스킬 api_refs 가 모두 반영된다.
    4. _inject_runtime_tools: orchestrator specs 에 infrastructure tool 전체를 추가한다.
    5. _filter_specs_for_sub_agent: 에이전트가 api_refs 를 가지면 화이트리스트와
       무관하게 infrastructure tool 들이 specs 에 포함된다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent.tools  # noqa: F401, E402 — register_tool 부수효과
from agent.harness import (  # noqa: E402
    _compose_orchestrator_system_prompt,
    _compose_sub_agent_system_prompt,
    _filter_specs_for_sub_agent,
    _inject_runtime_tools,
)
from agent.harness.loop import _build_orchestrator_specs  # noqa: E402
from agent.models import AgentState, ToolSpec  # noqa: E402
from agent.registries.agents import Agent, AgentMeta, AgentRegistry  # noqa: E402
from agent.registries.skills import Skill, SkillMeta  # noqa: E402
from agent.registries.tools import ToolRegistry  # noqa: E402
from agent.runtime import introspect  # noqa: E402
from agent.tools.runtime import INFRASTRUCTURE_TOOL_NAMES  # noqa: E402
from tests._runner import run_tests  # noqa: E402


def _setup() -> None:
    os.environ["APP_ALLOWED_LIBRARIES"] = "json,statistics"
    introspect.clear_cache()


def test_skill_meta_default_api_refs_empty() -> None:
    _setup()
    meta = SkillMeta(name="dummy")
    assert meta.api_refs == [], "기본값은 빈 리스트여야 함"


def test_skill_meta_parses_api_refs() -> None:
    _setup()
    meta = SkillMeta(name="library_skill", api_refs=["json.loads", "statistics.mean"])
    assert meta.api_refs == ["json.loads", "statistics.mean"]


def test_agent_meta_default_api_refs_empty() -> None:
    _setup()
    meta = AgentMeta(name="x", description="y")
    assert meta.api_refs == []


def test_agent_meta_parses_api_refs() -> None:
    _setup()
    meta = AgentMeta(
        name="data_agent",
        description="데이터 분석",
        api_refs=["statistics"],
    )
    assert meta.api_refs == ["statistics"]


def test_orchestrator_prompt_includes_api_section_when_skill_has_refs() -> None:
    _setup()
    skill = Skill(
        meta=SkillMeta(name="json_skill", api_refs=["json.loads"]),
        source_path="(test)",
        body="JSON 처리용 SKILL 본문.",
    )
    composed = _compose_orchestrator_system_prompt(
        base="BASE",
        skills=[skill],
        state=AgentState(),
        agent_registry=AgentRegistry(),
    )
    assert "Available Library APIs" in composed
    assert "json.loads" in composed
    assert "JSON 처리용 SKILL 본문." in composed


def test_orchestrator_prompt_no_api_section_when_no_refs() -> None:
    _setup()
    skill = Skill(
        meta=SkillMeta(name="plain_skill"),
        source_path="(test)",
        body="api_refs 없는 SKILL.",
    )
    composed = _compose_orchestrator_system_prompt(
        base="BASE",
        skills=[skill],
        state=AgentState(),
        agent_registry=AgentRegistry(),
    )
    assert "Available Library APIs" not in composed


def test_subagent_prompt_includes_api_section_from_agent_refs() -> None:
    _setup()
    agent = Agent(
        meta=AgentMeta(
            name="data_agent",
            description="데이터 분석",
            api_refs=["json.dumps"],
        ),
        source_path="(test)",
        body="에이전트 본문.",
    )
    composed = _compose_sub_agent_system_prompt(
        base="BASE", agent=agent, skill_bodies=[]
    )
    assert "Available Library APIs" in composed
    assert "json.dumps" in composed


def test_subagent_prompt_merges_agent_and_skill_refs() -> None:
    _setup()
    agent = Agent(
        meta=AgentMeta(name="data_agent", description="d", api_refs=["json.dumps"]),
        source_path="(test)",
        body="agent body",
    )
    skill = Skill(
        meta=SkillMeta(name="s", api_refs=["statistics.mean"]),
        source_path="(test)",
        body="skill body",
    )
    composed = _compose_sub_agent_system_prompt(
        base="BASE", agent=agent, skill_bodies=[skill]
    )
    assert "json.dumps" in composed
    assert "statistics.mean" in composed


def test_inject_runtime_tools_adds_all_infra_tools() -> None:
    _setup()
    registry = ToolRegistry()
    base_specs: list[ToolSpec] = []
    out = _inject_runtime_tools(base_specs, registry)
    out_names = {s.name for s in out}
    assert INFRASTRUCTURE_TOOL_NAMES.issubset(out_names), (
        f"infrastructure tools 누락: 기대 {INFRASTRUCTURE_TOOL_NAMES}, 실제 {out_names}"
    )


def test_inject_runtime_tools_does_not_duplicate() -> None:
    _setup()
    registry = ToolRegistry()
    rt = registry.get("call_function")
    assert rt is not None, "call_function 이 등록되어 있어야 함"
    pre = [ToolSpec(name=rt.name, description=rt.description, parameters=rt.parameters)]
    out = _inject_runtime_tools(pre, registry)
    call_function_count = sum(1 for s in out if s.name == "call_function")
    assert call_function_count == 1, "중복 추가되면 안 됨"


def test_filter_specs_for_sub_agent_exposes_runtime_when_agent_has_api_refs() -> None:
    _setup()
    registry = ToolRegistry()
    all_specs = registry.specs()
    # 화이트리스트는 매우 좁게 (only complete_subagent).
    agent = Agent(
        meta=AgentMeta(
            name="data_agent",
            description="d",
            tools=["complete_subagent"],
            api_refs=["json.loads"],
        ),
        source_path="(test)",
        body="x",
    )
    filtered = _filter_specs_for_sub_agent(all_specs, agent)
    names = {s.name for s in filtered}
    # complete_subagent 는 화이트리스트로 들어옴.
    assert "complete_subagent" in names
    # api_refs 가 있으므로 infrastructure tools 가 자동 노출.
    assert "call_function" in names
    assert "eval_expression" in names


def test_filter_specs_for_sub_agent_without_api_refs_respects_whitelist() -> None:
    _setup()
    registry = ToolRegistry()
    all_specs = registry.specs()
    agent = Agent(
        meta=AgentMeta(
            name="plain_agent",
            description="d",
            tools=["complete_subagent"],
        ),
        source_path="(test)",
        body="x",
    )
    filtered = _filter_specs_for_sub_agent(all_specs, agent)
    names = {s.name for s in filtered}
    assert names == {"complete_subagent"}, (
        f"api_refs 없으면 화이트리스트만. 실제: {names}"
    )


def test_filter_specs_for_sub_agent_skill_api_refs_also_triggers_runtime() -> None:
    """에이전트는 api_refs 가 없지만 학습 SKILL 이 api_refs 를 가지면 runtime 노출."""
    _setup()
    registry = ToolRegistry()
    all_specs = registry.specs()
    agent = Agent(
        meta=AgentMeta(
            name="data_agent",
            description="d",
            tools=["complete_subagent"],
        ),
        source_path="(test)",
        body="x",
    )
    skill = Skill(
        meta=SkillMeta(name="s", api_refs=["json.loads"]),
        source_path="(test)",
        body="skill body",
    )
    filtered = _filter_specs_for_sub_agent(all_specs, agent, [skill])
    names = {s.name for s in filtered}
    assert "call_function" in names, "SKILL api_refs 로도 runtime 노출되어야 함"


# ---------------------------------------------------------------------------
# 오케스트레이터 baseline api_refs (APP_ORCHESTRATOR_API_REFS)
# ---------------------------------------------------------------------------


def test_orchestrator_baseline_injects_api_section_without_skill_refs() -> None:
    """api_refs 없는 SKILL 만 활성이어도 baseline 으로 API 섹션이 노출된다."""
    _setup()
    skill = Skill(
        meta=SkillMeta(name="plain_skill"),
        source_path="(test)",
        body="api_refs 없는 SKILL.",
    )
    composed = _compose_orchestrator_system_prompt(
        base="BASE",
        skills=[skill],
        state=AgentState(),
        agent_registry=AgentRegistry(),
        baseline_api_refs=["json.loads"],
    )
    assert "Available Library APIs" in composed
    assert "json.loads" in composed


def test_orchestrator_baseline_works_with_no_skills() -> None:
    """활성 SKILL 이 하나도 없어도 baseline 만으로 API 섹션이 노출된다."""
    _setup()
    composed = _compose_orchestrator_system_prompt(
        base="BASE",
        skills=[],
        state=AgentState(),
        agent_registry=AgentRegistry(),
        baseline_api_refs=["statistics.mean"],
    )
    assert "Available Library APIs" in composed
    assert "statistics.mean" in composed


def test_orchestrator_baseline_empty_keeps_legacy_behavior() -> None:
    """baseline 빈 값 + api_refs 없는 SKILL → API 섹션 없음(회귀 보장)."""
    _setup()
    skill = Skill(
        meta=SkillMeta(name="plain_skill"),
        source_path="(test)",
        body="x",
    )
    composed = _compose_orchestrator_system_prompt(
        base="BASE",
        skills=[skill],
        state=AgentState(),
        agent_registry=AgentRegistry(),
        baseline_api_refs=[],
    )
    assert "Available Library APIs" not in composed


def test_orchestrator_baseline_bad_ref_no_exception() -> None:
    """baseline 에 허용 목록 밖/존재하지 않는 ref → 예외 없이 해당 항목만 누락."""
    _setup()
    # 'nonexistent_pkg' 는 APP_ALLOWED_LIBRARIES 밖 → LibraryAccessError 가 내부에서
    # 잡혀 skip. 섹션은 비어 결과 텍스트에 포함되지 않는다.
    composed = _compose_orchestrator_system_prompt(
        base="BASE",
        skills=[],
        state=AgentState(),
        agent_registry=AgentRegistry(),
        baseline_api_refs=["nonexistent_pkg.foo"],
    )
    assert "Available Library APIs" not in composed


def test_orchestrator_specs_always_expose_infra_tools() -> None:
    """오케스트레이터 specs 에는 infrastructure 메타 도구가 항상 노출된다.

    registry.specs() 가 등록된 전 도구를 반환하므로 baseline/api_refs 와 무관하게
    call_function 등은 오케스트레이터에 항상 있다. 따라서 baseline api_refs 가
    오케스트레이터에 추가로 제공하는 것은 '도구'가 아니라 prompt 의 docstring 섹션이다
    (이 설계 전제가 깨지면 baseline 기능 의미가 바뀌므로 회귀 가드).
    """
    _setup()
    registry = ToolRegistry()
    skill = Skill(meta=SkillMeta(name="plain_skill"), source_path="(test)", body="x")
    specs = _build_orchestrator_specs(registry, [skill], has_agents=True)
    names = {s.name for s in specs}
    assert INFRASTRUCTURE_TOOL_NAMES.issubset(names), (
        f"오케스트레이터는 infra 메타 도구를 항상 노출해야 함: {names}"
    )


if __name__ == "__main__":
    run_tests(globals())
