"""Dev 전용 디버그 트레이스 패키지.

실제 LLM provider 연결 시 에이전트의 의도치 않은 행동·루프·오류 원인을 추적하기 위해,
턴마다 provider in/out(프롬프트 전문·raw 응답)과 하니스 결정점(루프가드·슬롯가드·
wind-down 등)을 단일 타임라인 JSONL 로 기록한다. ``APP_DEBUG_TRACE=true`` 인 dev
환경에서만 활성화되며 frozen EXE 에서는 강제 비활성이다 (agent.config.DEBUG_TRACE_ENABLED).
"""
