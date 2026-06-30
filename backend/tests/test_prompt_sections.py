"""프롬프트 섹션 렌더러 단위 테스트 — `# 이전 진행 요약` (objective + progress_summary).

순수 함수라 harness 없이 AgentState 만으로 검증한다. objective/progress_summary 가
둘 다 비면 섹션 생략, 하나라도 있으면 렌더 + namespace 복원 너지 한 줄 포함.
"""

from __future__ import annotations

from agent.harness.prompt.sections import _render_progress_summary_section
from agent.models import AgentState


def test_progress_section_none_when_both_empty() -> None:
    assert _render_progress_summary_section(AgentState()) is None


def test_progress_section_renders_objective_only() -> None:
    state = AgentState(objective="지역별 Q4 매출 비교 리포트")
    out = _render_progress_summary_section(state)
    assert out is not None
    assert "# 이전 진행 요약" in out
    assert "지역별 Q4 매출 비교 리포트" in out
    assert "load_artifact" in out  # namespace 휘발 복원 너지
    assert "지금까지의 진행" not in out  # progress 없으면 그 줄은 생략


def test_progress_section_renders_summary_only() -> None:
    state = AgentState(progress_summary="지역 X 제외 합의, 매출 parquet 저장 완료")
    out = _render_progress_summary_section(state)
    assert out is not None
    assert "지금까지의 진행: 지역 X 제외 합의" in out
    assert "원래 목표" not in out


def test_progress_section_renders_both() -> None:
    state = AgentState(objective="목표 G", progress_summary="진행 P")
    out = _render_progress_summary_section(state)
    assert out is not None
    assert "원래 목표: 목표 G" in out
    assert "지금까지의 진행: 진행 P" in out
