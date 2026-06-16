# 프로젝트 소개 자료 (Overview)

이 폴더는 **프로젝트를 처음 접하는 사람에게 프로젝트 자체를 설명하기 위한 자료**다.
`docs/` 의 다른 문서들이 "에이전트를 커스터마이징하는 개발자"를 위한 참고서라면,
이 폴더는 "이 프로젝트가 무엇이고 어떻게 동작하는가"를 큰 그림부터 차례로 설명한다.

각 문서는 **섹션 단위(`##`)로 큰 그림부터 차례로** 읽을 수 있게 구성되어 있다.

## 읽는 순서

| 순서 | 문서 | 답하는 질문 |
|---|---|---|
| ① | [01-project-overview.md](01-project-overview.md) | 무엇을 만드는 프로젝트인가? 기술 스택·3계층 구조·디렉터리 |
| ② | [02-agent-and-extensibility.md](02-agent-and-extensibility.md) | 에이전트는 어떻게 정의·확장하는가? PROMPTS/SKILLS/AGENTS, 확장 시스템 |
| ③ | [03-ux-ui.md](03-ux-ui.md) | 최종 사용자는 어떤 화면에서 어떤 기능을 쓰는가? |
| ④ | [04-backend-flow.md](04-backend-flow.md) | 백엔드는 내부적으로 어떻게 동작하는가? 어떤 모듈·도구가 있는가? |
| ⑤ | [05-build-and-update.md](05-build-and-update.md) | 어떻게 빌드·배포·자동 업데이트되는가? `.env` 환경 변수 전체 목록 |

## 더 깊이 들어가려면

- 에이전트 확장(SKILLS/AGENTS/도구 추가) → [docs/guides/README.md](../guides/README.md)
- 하니스 내부 흐름 (패키지 구조·이벤트·상태) → [docs/harness/README.md](../harness/README.md)
- 아키텍처 세부 결정 사항 → `.claude/rules/*.md`
