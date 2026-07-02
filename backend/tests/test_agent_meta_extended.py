"""AgentMeta 필드 — 백워드 호환·프롬프트 주입·priority tie-break 라우팅 검증."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.harness import (  # noqa: E402
    _compose_orchestrator_system_prompt,
    _compose_sub_agent_system_prompt,
)
from agent.models import AgentState  # noqa: E402
from agent.registries.agents import Agent, AgentMeta, AgentRegistry  # noqa: E402
from tests._runner import run_tests  # noqa: E402


def test_agent_meta_optional_fields_default_to_none() -> None:
    """기존 .md 파일(role/goal/when_to_delegate 없음) 호환성 검증."""
    meta = AgentMeta(name="legacy_agent", description="설명")
    assert meta.role is None
    assert meta.goal is None
    assert meta.when_to_delegate is None


def test_agent_meta_accepts_extended_fields() -> None:
    meta = AgentMeta(
        name="modern_agent",
        description="설명",
        role="시니어 분석가",
        goal="정확한 결과를 전달한다",
        when_to_delegate="분석 요청이 들어오면 위임",
    )
    assert meta.role == "시니어 분석가"
    assert meta.goal == "정확한 결과를 전달한다"
    assert "위임" in meta.when_to_delegate


def test_orchestrator_prompt_renders_extended_fields_when_present() -> None:
    extended_meta = AgentMeta(
        name="extended_agent",
        description="설명",
        skills=["some_skill"],
        role="QA 엔지니어",
        goal="회귀 버그를 조기에 발견한다",
        when_to_delegate="테스트 작성·실행 요청 시 위임",
    )
    legacy_meta = AgentMeta(name="legacy_agent", description="구식 설명")

    agent_registry = MagicMock()
    agent_registry.list_meta.return_value = [extended_meta, legacy_meta]

    prompt = _compose_orchestrator_system_prompt(
        base="BASE",
        skills=[],
        state=AgentState(),
        agent_registry=agent_registry,
    )

    # 확장 필드는 값이 있을 때만 렌더링된다.
    assert "Role: QA 엔지니어" in prompt
    assert "Goal: 회귀 버그를 조기에 발견한다" in prompt
    assert "When to delegate: 테스트 작성·실행 요청 시 위임" in prompt

    # legacy 에이전트는 Role/Goal 헤더가 없어야 한다 — 같은 prompt 안에 둘 다 있으므로
    # 'Role: QA 엔지니어' 다음에 'Role:' 가 또 등장하지 않는지 확인한다.
    role_count = prompt.count("Role:")
    assert role_count == 1, (
        f"legacy 에이전트에는 Role 헤더가 없어야 함 — 총 {role_count}개 등장"
    )


def test_sub_agent_prompt_injects_role_and_goal_at_top() -> None:
    agent = Agent(
        meta=AgentMeta(
            name="qa_agent",
            description="설명",
            role="QA 엔지니어",
            goal="회귀를 조기 발견",
        ),
        source_path="",
        body="당신은 테스트 작성 전문가입니다.",
    )

    prompt = _compose_sub_agent_system_prompt(
        base="BASE_AND_TOOLS_GUIDE",
        agent=agent,
        skill_bodies=[],
    )

    assert "qa_agent" in prompt
    assert "- Role: QA 엔지니어" in prompt
    assert "- Goal: 회귀를 조기 발견" in prompt
    # body 도 포함된다.
    assert "테스트 작성 전문가" in prompt
    # Role 헤더가 body 보다 먼저 등장해야 한다.
    assert prompt.index("Role:") < prompt.index("테스트 작성 전문가")


def test_sub_agent_prompt_legacy_agent_has_no_role_block() -> None:
    """role/goal 없는 기존 에이전트는 헤더 없이 본문만 렌더링되어야 한다."""
    agent = Agent(
        meta=AgentMeta(name="legacy", description="설명"),
        source_path="",
        body="레거시 본문",
    )

    prompt = _compose_sub_agent_system_prompt(
        base="BASE",
        agent=agent,
        skill_bodies=[],
    )

    assert "Role:" not in prompt
    assert "Goal:" not in prompt
    assert "레거시 본문" in prompt


def _write_agent(dir_path: Path, filename: str, *, name: str, priority: int) -> None:
    """priority tie-break 테스트용 최소 AGENTS/*.md 파일을 쓴다(shared_skill 전담)."""
    body = (
        "---\n"
        f"name: {name}\n"
        "description: 우선순위 테스트 에이전트\n"
        "skills:\n"
        "  - shared_skill\n"
        f"priority: {priority}\n"
        "---\n\n"
        "본문.\n"
    )
    (dir_path / filename).write_text(body, encoding="utf-8")


def test_list_meta_orders_by_priority_desc() -> None:
    """priority 높은 에이전트가 앞선다 — 파일명 순서를 이긴다."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        # 파일명 순(alpha_ < zeta_)이 priority 순과 반대가 되도록 배치 —
        # 정렬이 파일명이 아니라 priority 를 따르는지 확인한다.
        _write_agent(tmp, "alpha_low.md", name="alpha_low", priority=5)
        _write_agent(tmp, "zeta_high.md", name="zeta_high", priority=9)
        reg = AgentRegistry(agents_dir=tmp)
        reg.load()
        names = [m.name for m in reg.list_meta()]

    assert names == ["zeta_high", "alpha_low"]


def test_list_meta_equal_priority_keeps_filename_order() -> None:
    """동일 priority 는 파일명 순(로드 순)을 유지한다 — stable sort."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _write_agent(tmp, "a_agent.md", name="a_agent", priority=5)
        _write_agent(tmp, "b_agent.md", name="b_agent", priority=5)
        reg = AgentRegistry(agents_dir=tmp)
        reg.load()
        names = [m.name for m in reg.list_meta()]

    assert names == ["a_agent", "b_agent"]


def test_case3_mapping_picks_highest_priority_agent() -> None:
    """동일 스킬을 두 에이전트가 등록하면 Case 3 매핑은 priority 높은 쪽으로 확정된다.

    list_meta() 가 priority 내림차순을 반환한다는 계약 위에서, compose 의
    setdefault(첫 등록 유지)가 최고 priority 에이전트를 전담자로 고르는지 검증한다.
    """
    high = AgentMeta(
        name="high_prio_agent", description="높음", skills=["shared"], priority=9
    )
    low = AgentMeta(
        name="low_prio_agent", description="낮음", skills=["shared"], priority=5
    )

    agent_registry = MagicMock()
    # list_meta() 계약대로 priority 내림차순으로 반환.
    agent_registry.list_meta.return_value = [high, low]

    prompt = _compose_orchestrator_system_prompt(
        base="BASE",
        skills=[],
        state=AgentState(),
        agent_registry=agent_registry,
    )

    assert "## Case 3 결정론 매핑" in prompt
    assert "'shared' 트리거가 들어오면 반드시 `high_prio_agent` 에게" in prompt
    # low_prio 는 shared 의 전담자로 등장하지 않는다.
    assert "'shared' 트리거가 들어오면 반드시 `low_prio_agent` 에게" not in prompt


if __name__ == "__main__":
    run_tests(globals())
