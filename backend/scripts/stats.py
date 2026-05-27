"""Mock 시나리오 및 실제 분석 작업에서 사용하는 기본 통계 유틸리티.

`api_refs` 를 통해 SKILL 에 노출되며, harness 가 `call_function` /`eval_expression` /
`exec_code` 메타 도구로 LLM 에게 제공한다. stdlib `statistics` 만 사용해 외부 의존성
없음 — pandas/numpy 미설치 환경에서도 동작한다.
"""

from statistics import mean, median, stdev


def compute_summary_stats(data: list[float]) -> dict[str, float]:
    """주어진 숫자 리스트의 기본 요약 통계량을 계산한다.

    Args:
        data: 분석 대상 1차원 숫자 리스트. 비어 있으면 ValueError.

    Returns:
        count·mean·median·stdev·min·max 6개 항목의 dict.
        표본 1개일 땐 stdev=0.0 으로 처리한다 (statistics.stdev 가 요구하는 n≥2 회피).

    Raises:
        ValueError: data 가 비어 있을 때.

    Example:
        >>> compute_summary_stats([1.0, 2.0, 3.0, 4.0, 5.0])
        {'count': 5, 'mean': 3.0, 'median': 3.0, 'stdev': 1.5811, 'min': 1.0, 'max': 5.0}
    """
    if not data:
        raise ValueError("data 는 비어 있을 수 없다")

    return {
        "count": len(data),
        "mean": round(mean(data), 4),
        "median": round(median(data), 4),
        "stdev": round(stdev(data), 4) if len(data) > 1 else 0.0,
        "min": min(data),
        "max": max(data),
    }
