"""기본 내장 도구 — 실시간 정보 조회."""

from datetime import datetime

from agent.registries.tools import register_tool


@register_tool(
    description=(
        "현재 시각(로컬 타임존)을 ISO 8601 문자열로 반환한다. "
        "When to use: 사용자가 '지금 몇 시'·'오늘 날짜' 등 현재 시각을 묻거나, "
        "보고서·로그에 타임스탬프를 박아야 할 때. "
        "When NOT to use: 과거·미래 시점이 필요할 때(이 도구는 호출 시점만 반환). "
        "Expected chaining: 단독 호출이 일반적. 결과를 그대로 사용자에게 자연어로 회신하면 된다."
    ),
    timeout_seconds=5,
)
async def now() -> str:
    """사용자가 시각을 물을 때 호출하는 데모 도구."""
    return datetime.now().isoformat(timespec="seconds")
