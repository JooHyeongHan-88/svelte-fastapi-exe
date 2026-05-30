# 개발 가이드

이 디렉터리는 에이전트 동작을 커스터마이징할 때 필요한 문서들을 담고 있다.

## 문서 목록

| 파일 | 대상 | 핵심 내용 |
|---|---|---|
| [skills.md](skills.md) | `SKILLS/*.md` 작성자 | Front Matter 필드, 트리거 매칭 원리, 본문 작성 패턴 |
| [agents.md](agents.md) | `AGENTS/*.md` 작성자 | Front Matter 필드, Case 3 라우팅, 페르소나 작성법, 서브 에이전트 제약 |
| [prompts.md](prompts.md) | `PROMPTS/*.md` 수정자 | 파일별 역할, 합성 순서, 핫리로드 정책 |
| [builtin-tools.md](builtin-tools.md) | SKILL·AGENT 본문 작성자 | add_todo/complete_todo/ask_user/call_sub_agent/complete_subagent 사용법 |
| [charts.md](charts.md) | `display_chart` 를 쓰는 SKILL·AGENT 작성자 | 차트 유형(mark)별 encoding, parquet+spec 파이프라인, brush 필터가 되는 차트 |
| [library-runtime.md](library-runtime.md) | 외부 Python 라이브러리 노출 | `api_refs` 패턴, 7개 메타 도구, 세션 namespace, 보안 모델 |
| [mock-scenarios.md](mock-scenarios.md) | Mock Provider 개발자 | 전체 시나리오 목록·트리거·흐름·산출물 경로·신규 시나리오 추가 방법 |

## 빠른 참조

### 새 기능을 추가하려면

| 목표 | 방법 |
|---|---|
| 특정 키워드에 반응하는 행동 지침 추가 | `SKILLS/` 에 `.md` 파일 추가 → [skills.md](skills.md) |
| 특정 도메인 전담 서브 에이전트 추가 | `AGENTS/` 에 `.md` 파일 추가 → [agents.md](agents.md) |
| 에이전트 기본 페르소나/응답 스타일 변경 | `PROMPTS/base.md` 수정 → [prompts.md](prompts.md) |
| 새 사내 API 도구 등록 | `backend/agent/tools/` 에 `.py` 파일 추가 → `.claude/rules/agent_extension.md` 참조 |
| 외부 Python 라이브러리를 Agent 가 동적으로 사용 | `.env` 의 `APP_ALLOWED_LIBRARIES` 등록 + SKILL/AGENT 에 `api_refs` 추가 → [library-runtime.md](library-runtime.md) |
| 데이터를 차트로 시각화 (`display_chart`) | parquet + `charts.spec.json` 작성 → [charts.md](charts.md) |

### 작업 흐름이 UI 에 표시되려면

작업이 `TodoProgress` 체크리스트로 표시되려면 SKILL 본문에 `add_todo` 패턴이 있어야 한다.
`add_todo` 없이 도구만 호출하면 도구 상태 라벨(`🔧 fetch_sales 호출 중...`)만 표시된다.

→ [builtin-tools.md — add_todo](builtin-tools.md#add_todo) 참조
