# [2] Mock Provider 시나리오 전면 개편 및 Harness 검증 고도화

현재 우리 프로젝트의 Harness는 `builtin tools`, `PROMPTS`, `SKILLS`, `AGENTS`의 조합으로 구현된 자율형 다중 에이전트 시스템(Autonomous Multi-Agent System)입니다. 
하지만 현재 구현된 `Mock Provider`의 시나리오들은 체계적인 아키텍처 검증보다는, UI/UX 테스트를 위해 그때그때 단편적으로 만들어진 경향이 있습니다.

아래의 지침을 읽고, **실제 LLM이 이 Harness 위에서 완벽한 AI Agent로서 동작할 수 있는지 검증하기 위한 목적**으로 Mock 시나리오를 전면 개편하고 고도화할 실행 계획(Plan)을 수립해 주세요. 깊이 고민하여 실제 LLM의 도구 호출 루프(Tool-call Loop)와 추론 과정을 완벽히 모방해 주어야 합니다.

## 1. 개편 목적 (Objective)
- **Harness 스트레스 테스트**: 이 작업의 진정한 목적은, 실제 최고 수준의 LLM(Opus, GPT-4 등)을 연결했을 때 우리 시스템의 Harness(라우팅, 상태 관리, 도구 호출 루프)가 무너지지 않고 AI Agent의 작업을 끝까지 완수해 낼 수 있는지를 가상으로 검증하는 것입니다.
- **Agent Loop 검증**: LLM이 추론(Reasoning)하고, 계획을 세우고(`add_todo`), 도구를 호출하고 그 결과를 바탕으로 다음 행동을 결정하는 **연속적인 Loop가 얼마나 탄탄한지 확인하고 약점을 찾아 개선**해야 합니다.

## 2. 설계 원칙 (Principles)
- **완벽한 LLM 모방 (Strict Simulation)**: Mock은 실제 LLM의 행동 패턴(`delta` 스트리밍, `reasoning` 블록 생성, 정확한 JSON Schema에 맞춘 `tool_call` 등)을 어떠한 편법 없이 그대로 모방하여 Yield 해야 합니다.
- **Harness와 Mock의 역할 분리**: `builtin tools`, `SKILLS`, `AGENTS`는 환경(Environment)이고 Mock은 행위자(Actor)입니다. Mock 시나리오 자체에 비즈니스 로직을 하드코딩해서는 안 되며, **"가상의 LLM이 이 도구들을 파악하고 자율적으로 조합해서 사용하는 흐름"**을 만들어야 합니다. 
- **환경(SKILLS/AGENTS)의 주도적 리팩토링**: 만약 현재 구현된 `SKILLS`나 `AGENTS`가 너무 단순해서 LLM Mock의 복합적인 가상 시나리오(예: 에러 복구, 다중 에이전트 체이닝, 산출물 직접 저장 등)를 테스트하기 어렵다면, **당신(Claude Code)의 판단하에 SKILLS와 AGENTS를 과감히 수정, 삭제, 또는 신규 추가**하십시오.
- **복합 시나리오 (Complex Chains)**: 단일 도구 호출로 끝나는 시나리오보다는, "데이터 수집 → 산출물 저장(`save_artifact` 등) → 시각화(`display_chart`) → 요약 보고" 처럼 **여러 도구와 서브 에이전트가 복합적으로 얽힌 체인(Chain)**을 최우선으로 설계해야 합니다.

## 3. 요구 사항 및 Action Items
위 원칙에 따라 다음 작업에 대한 구체적인 **실행 계획(Implementation Plan)**을 먼저 제시하고, 승인 후 작업을 진행해 주세요.

1. **가상 시나리오 전면 개편안 설계**: 단순한 Echo나 UI 토글을 넘어, Harness의 엣지 케이스(예: 도구 호출 실패 시 재시도, 서브 에이전트 위임 후 복귀, 다중 Tool 동시 호출 등)를 테스트할 수 있는 강력한 Mock 시나리오들을 기획하세요.
2. **SKILLS / AGENTS 고도화**: 기획한 복합 시나리오가 제대로 동작할 수 있도록, 이를 뒷받침할 현실적이고 고도화된 `SKILLS`와 `AGENTS` 메타데이터(Role, Goal, 위임 조건 등)를 리팩토링하세요. (필요하다면 앞서 논의했던 산출물 저장 권한 등도 고려할 것).
3. **문서화 최신화**: 모든 시나리오와 환경 설정이 완성되면, 이를 바탕으로 `@docs/mock-scenarios.md` 문서를 완벽하게 업데이트하여 시스템 작동 원리를 명세화하세요.
