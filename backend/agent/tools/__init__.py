"""사내 API 도구 모음 — `@register_tool` 데코레이터로 자기등록한다.

이 패키지가 import 되는 순간 모든 서브모듈이 한 번에 로드되며, 데코레이터의
부수효과로 `agent.registries.tools._REGISTRY` 가 채워진다. 새 API 를 도구로
노출하려면 이 디렉토리에 새 `.py` 파일을 만들어 데코레이터를 붙이기만 하면 된다.

부팅 진입점: `backend/main.py` 가 `import agent.tools` 한 줄로 트리거.
"""

from agent.tools import (  # noqa: F401 — 등록 부수효과
    artifact,
    builtin,
    clarify,
    demo,
    dispatch,
    planner,
    visualize,
)

__all__: list[str] = []
