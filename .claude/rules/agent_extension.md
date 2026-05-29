# 에이전트 확장 패턴

## 라이브러리 노출 패턴 선택

외부 Python 라이브러리(`sensordx` 등)를 Agent 에게 노출할 때 두 가지 패턴이 있다:

| 패턴 | 언제 |
|---|---|
| **A. `@register_tool` 1:1 매핑** | 함수가 5개 이하, 인자/반환 타입이 단순(`str`/`int`/`dict`/...), 시그니처가 LLM 에 명시적으로 보이는 게 더 안전한 경우 |
| **B. `api_refs` 메타 도구** | API 가 많음, DataFrame/ndarray 등 객체 반환·체이닝 필요, 라이브러리가 자주 업데이트되어 wrapper 유지보수 비용이 큼 |

대부분의 도메인 라이브러리(특히 데이터 분석)는 **B 패턴**이 적합하다. `.env` 의 `APP_ALLOWED_LIBRARIES` 에 패키지 루트 한 줄, SKILL/AGENT 의 `api_refs` 에 노출하고 싶은 함수만 적으면 끝. 자세한 내용은 [docs/library-runtime.md](../../docs/library-runtime.md).

A 패턴은 아래 절차를 따른다.

### `backend/scripts/` — 프로젝트 전용 Python 스크립트 패키지

`.venv` 에 설치하기엔 과한 경량 유틸리티나 도메인 전용 로직은 `backend/scripts/` 에 Python 파일로 추가한다.

```
backend/scripts/
  __init__.py        ← 반드시 존재해야 Python 패키지로 인식
  my_util.py
  data_transform.py
```

**사용 방법**: `APP_ALLOWED_LIBRARIES=scripts` + SKILL 의 `api_refs`:

```yaml
api_refs:
  - scripts.my_util.process_data
```

**EXE 자동 번들링**: `App.spec` 이 `collect_submodules('scripts')` 로 자동 수집. 파일 추가만으로 다음 빌드에 반영된다 — spec 파일 수정 불필요.

> `scripts` 는 `APP_ALLOWED_LIBRARIES` 에서 `collect_all()` 대신 `collect_submodules()` 로 수집됨 (App.spec 에 명시적으로 처리됨).

---

## 새 API를 Tool로 등록하기

`backend/agent/tools/` 에 새 `.py` 파일을 만들고 `@register_tool` 데코레이터를 붙이기만 하면 된다.
부팅 시 `agent/tools/__init__.py` 가 모든 서브모듈을 import 해 자동 등록한다.

```python
# backend/agent/tools/sales.py
from datetime import date
from typing import Annotated
from agent.models import ToolResult
from agent.registries.tools import register_tool

@register_tool(
    description="매출 데이터를 기간으로 조회한다.",
    slot_prompts={"date_from": "조회 시작일(YYYY-MM-DD)을 알려주세요"},
    timeout_seconds=15,
)
async def fetch_sales(
    date_from: Annotated[date, "조회 시작일"],
    date_to: Annotated[date, "조회 종료일"],
) -> ToolResult:
    rows = await my_db.fetch_sales(date_from, date_to)
    return ToolResult(content=f"{len(rows)} rows fetched", data={"rows": rows})
```

### 규칙

- 함수는 반드시 `async`. 동기 함수는 등록 시 `TypeError`.
- 각 파라미터에 `Annotated[T, "설명"]` 로 의미 부착 — JSON Schema description 으로 LLM에 노출.
- 반환값은 `str` 또는 `ToolResult`. dict 등 임의 객체는 `str(...)` 로 폴백 변환.
- 인자 검증은 Pydantic이 자동. **필수 슬롯 누락**(값 부재)만 `AskUserEvent` 로 사용자에게 재질문하고, **형식·타입 오류**(값은 줬는데 모양이 틀림, e.g. `date_from="오늘"`·문자열 자리 dict)는 `invalid_message` 로 LLM 에 도구 에러를 회신해 self-correct 시킨다 (사용자 미개입). 분기 로직은 `guard._split_errors`.
- `sentinel=True` 는 harness가 분기 처리하는 도구 (`add_todo` 등) 전용. 함부로 쓰지 말 것.
- `slot_prompts` 딕셔너리는 파라미터 이름 → 사용자에게 보여줄 질문 문구 (**missing 슬롯에만** 적용; 형식 오류는 LLM 에 회신되므로 미사용). 지정하지 않으면 Pydantic 에러 메시지 그대로 사용.
- `timeout_seconds` 미지정 시 `APP_TOOL_DEFAULT_TIMEOUT` (30s) 적용.

### 도구 반환값 구조

```python
ToolResult(
    content="LLM context에 노출되는 텍스트 요약",
    data={"key": "value"},   # 프론트엔드 ToolResultEvent.data 로 전달 (선택)
    is_error=True,           # 에러 시 True — harness가 RCA 유도 메시지 자동 추가
)
```

---

## 새 서브 에이전트 등록하기

`AGENTS/` 에 새 `.md` 파일을 만들고 YAML Front Matter를 작성하면 된다.
서버 재시작 없이 dev에서는 핫리로드, frozen EXE는 재기동 필요.

```markdown
---
name: sales_agent
description: 매출·재고 관련 조회를 전담하는 서브 에이전트
skills:
  - sales_report      # SKILLS/ 에 동일 이름 파일 존재 시 Case 3 자동 라우팅
tools:
  - fetch_sales       # 빈 리스트면 전체 도구 노출
  - fetch_inventory
  - add_todo
  - complete_todo
priority: 5
---

당신은 영업 데이터 분석 전문가입니다.
...에이전트 페르소나 및 작업 지침...

## 종료 규약 (필수)
작업을 마칠 때 반드시 `complete_subagent` 도구를 호출한다.
```

### Front Matter 필드

| 필드 | 필수 | 설명 |
|---|---|---|
| `name` | ✅ | `call_sub_agent(agent_name=...)` 에서 사용하는 식별자. 영소문자+언더스코어 |
| `description` | ✅ | 오케스트레이터 카탈로그에 노출되는 한 줄 설명. 도메인 키워드 명확히 작성 |
| `skills` | 선택 | SKILLS 이름 등록 → 해당 트리거 매칭 시 오케스트레이터가 자동 위임 (Case 3) |
| `tools` | 선택 | 허용 도구 화이트리스트. **빈 리스트면 전체 도구 노출** |
| `priority` | 선택 | 동일 스킬 담당 에이전트 여럿일 때 우선순위 (기본 5) |

### 제약

- 서브 에이전트는 다시 `call_sub_agent` 를 호출할 수 없다 (4중 방어선으로 차단됨).
- 본문(페르소나)은 위임 시점에 lazy load — 부팅 비용 없음.
- `tools` 화이트리스트에 `add_todo` / `complete_todo` 를 포함시켜야 서브 에이전트도 자체 Plan 작성 가능.
- `complete_subagent` 는 `tools` 에 명시하지 않아도 harness가 항상 자동 주입.

---

## 새 LLM 프로바이더 추가하기

1. `backend/agent/providers/<name>.py` 생성 — `astream(messages, tools)` AsyncGenerator 구현
2. `backend/agent/providers/factory.py`의 `get_provider()` 에 분기 추가
3. `backend/settings/models.py`의 `Literal["mock", "openai_compatible", "dtgpt", "<name>"]`에 추가
   (`LLMSettings.provider`, `ProviderMeta.id`, `ConnectionTestRequest.provider` 세 곳)
4. `backend/api/settings.py`의 `list_providers()` 에 `ProviderMeta` 항목 추가

> 기존 `settings.json`에 새 provider Literal 값이 없으면 로드 시 Pydantic ValidationError 발생.
> `SettingsStore._load()` 의 구 포맷 마이그레이션 로직처럼 방어 코드 또는 기본값 처리 고려.
