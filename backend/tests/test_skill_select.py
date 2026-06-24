"""SkillRegistry trigger/이름 매칭 정밀도 — ASCII 토큰 경계 매칭 회귀 테스트 (C-1).

부분문자열 매칭은 짧은 ASCII 토큰에서 오탐('data'∈'metadata')을 내지만, 한글은
형태소가 공백 없이 붙으므로 경계를 강제하면 정상 매칭이 깨진다('데이터요약'의 '데이터').
ASCII 영숫자 토큰에만 경계를 적용하고 한글/혼합은 substring 을 유지하는지 검증한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.registries.skills import _keyword_hit  # noqa: E402
from tests._runner import run_tests  # noqa: E402


def test_ascii_token_word_boundary() -> None:
    # ASCII 토큰은 경계가 맞을 때만 — 'data' 가 'metadata' 안에선 미스.
    assert _keyword_hit("data", "이 data 를 분석") is True
    assert _keyword_hit("data", "metadata 를 봐") is False
    assert _keyword_hit("time", "sometimes 그래") is False


def test_case_insensitive() -> None:
    # 대소문자 무관 — 키워드/텍스트 모두 lower 기준.
    assert _keyword_hit("CSV", "csv 로드") is True


def test_korean_trigger_substring_preserved() -> None:
    # 한글 트리거는 글루된 형태소 안에서도 매칭(substring 유지).
    assert _keyword_hit("데이터", "데이터요약 해줘") is True
    assert _keyword_hit("요약", "데이터요약 해줘") is True


def test_ascii_korean_mixed_boundary() -> None:
    # ASCII 토큰이 한글에 붙어도 경계로 인정(한글은 [a-z0-9] 아님).
    assert _keyword_hit("csv", "csv파일 로드") is True
    # 앞에 ASCII 가 붙으면 경계 아님 → 미스.
    assert _keyword_hit("csv", "mycsv 말고") is False


def test_multiword_and_underscore_tokens() -> None:
    # 공백 토큰은 substring 경로, underscore 토큰은 경계 경로 — 둘 다 정확 매칭.
    assert _keyword_hit("종합 보고서", "종합 보고서 만들어") is True
    assert _keyword_hit("data_summary", "data_summary 실행") is True


def test_empty_keyword_misses() -> None:
    assert _keyword_hit("", "아무거나") is False
    assert _keyword_hit("   ", "아무거나") is False


if __name__ == "__main__":
    run_tests(globals())
