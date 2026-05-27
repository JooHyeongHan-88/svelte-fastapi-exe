# 라이브러리 런타임 (Library Runtime)

백엔드 `.venv` 에 설치된 외부 Python 라이브러리를 Agent 가 동적으로 사용하기 위한 baseline 인프라. 라이브러리의 모든 API 를 `@register_tool` 로 일일이 래핑할 필요 없이, SKILL 또는 AGENT 의 `api_refs` 한 줄로 LLM 이 해당 API 들의 시그니처와 docstring 을 인지하고, 8 개의 메타 도구로 직접 실행할 수 있다.

---

## 빠른 사용 예시

`sensordx` 라이브러리의 `load_df()` 함수를 SKILL 에서 사용한다고 가정.

### 1. 환경변수 설정 (`.env`)

```env
APP_ALLOWED_LIBRARIES=sensordx
```

### 2. SKILL 작성 (`SKILLS/sensor_max.md`)

```markdown
---
name: sensor_max
trigger: ["최대값", "max", "센서"]
description: 사용자가 준 xlsx 파일에서 센서 데이터를 로드하고 최대값을 구한다.
api_refs:
  - sensordx.utils.load_df
---

사용자가 입력한 파일 경로의 xlsx 데이터를 sensordx.utils.load_df 로 불러온 후
가장 큰 측정값을 사용자에게 한국어로 답변한다.
```

### 3. 결과

사용자가 "test.xlsx 에서 최대값 찾아줘" 라고 보내면:

1. `sensor_max` SKILL 매칭 → 시스템 프롬프트에 SKILL 본문 + `sensordx.utils.load_df` 의 시그니처·docstring 자동 주입
2. LLM 이 자체 planning 으로 `call_function("sensordx.utils.load_df", {"path": "test.xlsx"}, "df")` 호출 → `df` 가 namespace 에 저장
3. `eval_expression("df.max()")` 또는 `describe_variable("df")` 로 최대값 도출
4. 사용자에게 자연어로 답변

`call_function`/`eval_expression` 등은 SKILL 본문에 명시하지 않아도 `api_refs` 가 있으면 자동으로 LLM 에 노출된다.

---

## 보안 모델

### ALLOWED_LIBRARIES 화이트리스트

- `.env` 의 `APP_ALLOWED_LIBRARIES` CSV 에 등록된 패키지 루트 이름만 해석 가능.
- 화이트리스트 외 모듈 접근 시도는 `LibraryAccessError` 로 거부 (`os.system` 등 호출 불가).
- 모든 메타 도구 (`inspect_callable`, `list_module_members`, `call_function`) 가 이 가드를 거친다.

### eval_expression / exec_code 의 안전 builtins

신뢰된 단일 사용자 데스크탑 .exe 라는 위협 모델에 맞춰 **데이터 분석 친화적으로 완화**된 환경:

- **차단**: `exec`, `eval`, `compile` (재귀 코드 인젝션 방지) 와 `__import__` 의 무제한 사용.
- **허용**: 그 외 모든 public builtin (`open`, `print`, `getattr`, `hasattr`, `callable`, `vars`, `dir`, `iter`, `next`, ...).
- **import 후킹**: stdlib 안전 목록(`math`, `statistics`, `json`, `datetime`, `pathlib`, `re`, `collections`, `itertools`, `functools`, `decimal`, `random`, ...) + `APP_ALLOWED_LIBRARIES` 패키지만 통과. `os`/`sys`/`subprocess`/`socket`/`shutil` 등 시스템·외부 통신 모듈은 의도적으로 차단 (runaway 방지). 필요하면 `APP_ALLOWED_LIBRARIES` 에 추가하면 동일 경로로 허용된다.
- dunder (`__class__` 등) 우회를 완전히 막지는 않음. 진정한 sandbox 가 아니라 LLM 실수·runaway 방지 가드다. 더 엄격하게 필요하면 AST 검사 또는 RestrictedPython 도입 검토.

stdlib 안전 목록의 정확한 멤버는 `backend/agent/runtime/evaluator.py` 의 `_STDLIB_ALWAYS_ALLOWED` 참조.

---

## 8개의 메타 도구

각 도구는 `backend/agent/tools/runtime.py` 에 `@register_tool` 로 등록되어 있다. SKILL/AGENT 에 `api_refs` 가 하나라도 있으면 harness 가 specs 에 자동 주입.

### `inspect_callable(qualified_name)`

함수/클래스의 시그니처 + docstring 조회.

```json
{ "qualified_name": "sensordx.utils.load_df" }
```

반환: `"## sensordx.utils.load_df [function] (path: str, sheet: int = 0) -> DataFrame\n\n...docstring..."`

### `list_module_members(module_path)`

모듈의 public 함수/클래스 목록.

```json
{ "module_path": "sensordx.utils" }
```

반환: 각 멤버의 이름·종류·1줄 docstring.

### `call_function(qualified_name, kwargs, store_as)`

라이브러리 함수를 실행하고 결과를 세션 namespace 에 저장한다.

```json
{
  "qualified_name": "sensordx.utils.load_df",
  "kwargs": {"path": "test.xlsx", "sheet": 0},
  "store_as": "df"
}
```

- `store_as` 는 Python identifier 형식 (`df`, `df_clean`, `stats`).
- `kwargs` 값에 `"$varname"` 형태 문자열이 있고 namespace 에 같은 이름 변수가 있으면 그 값으로 자동 치환된다 (객체 체이닝).
- 동기/async 함수 모두 지원 (sync 는 `run_in_executor` 로 event loop 비차단).

### `eval_expression(expression, store_as="")`

namespace 변수를 사용한 짧은 Python 식 평가.

```json
{ "expression": "df['temperature'].max()", "store_as": "max_temp" }
```

- `store_as` 가 비어 있으면 결과 repr 만 반환, namespace 에 저장 안 함.
- 식 (expression) 한 줄만 가능. 다중 statement / 할당 / import 가 필요하면 `exec_code` 사용.

### `exec_code(code)`

다중 statement Python 코드를 실행. import + 변수 할당 + 제어 흐름 + 함수/클래스 정의가 한 번에 가능.

```json
{
  "code": "import pandas as pd\ndf = pd.read_csv('data.csv')\nstats = df.describe()\nprint(stats)"
}
```

- 기존 namespace 변수는 자동으로 local 변수로 노출된다.
- 실행 후 새로 생성/변경된 변수는 namespace 에 자동 저장 (모듈/함수/클래스는 제외).
- `print()` 등 stdout 출력은 캡쳐되어 결과 텍스트에 포함된다.
- import 는 stdlib safe-list + `APP_ALLOWED_LIBRARIES` 만 허용 (동일한 보안 모델).

### `list_namespace()`

현재 세션의 모든 변수 한 줄씩 요약.

반환:
```
- df: DataFrame (45.3KB, tier=memory) — DataFrame[1000 rows × 5 cols]
- max_temp: float (28 bytes, tier=memory) — 87.3
```

### `describe_variable(name)`

변수 한 건의 타입별 상세 요약.

| 타입 | 출력 |
|---|---|
| `pd.DataFrame` | shape + dtypes + head(5) |
| `pd.Series` | len + dtype + head(5) |
| `np.ndarray` | shape + dtype + min/max + first 10 elements |
| `list`/`tuple` | len + first 5 |
| `dict` | len + keys preview |
| 기타 | `repr` (1500자 제한) |

### `delete_variable(name)`

namespace 에서 변수 영구 삭제 (memory + disk 모두).

---

## 세션 namespace 모델

라이브러리 함수의 반환값 객체(DataFrame, ndarray 등)는 JSON 으로 직렬화할 수 없으므로 백엔드 메모리/디스크에 보관되고, LLM 에는 **변수 이름 핸들** 만 노출된다. 변수는 같은 세션 안에서만 유효하며 세션 종료 시 자동 정리.

### Tier 결정 (memory hot ↔ disk cold)

| tier | 조건 | 직렬화 포맷 |
|---|---|---|
| `memory` | `estimate_size(obj) < APP_NAMESPACE_MEMORY_THRESHOLD` (기본 10MB) | (없음) |
| `disk` | 임계 초과 | `pd.DataFrame` → parquet, `np.ndarray` → npy, 그 외 → pickle |

디스크 경로: `result/{sanitized_title}-{client_id[:8]}/_namespace/{var_name}.{ext}`

`load()` 호출 시 disk tier 도 자동 역직렬화 — LLM 은 어디에 저장됐는지 신경 쓸 필요 없다.

### LRU 한도

`APP_NAMESPACE_MAX_VARS` (기본 20) 를 초과하면 가장 오래된 변수가 완전 제거된다. `load()` 가 호출되면 그 변수는 다시 최신으로 갱신.

### Lifecycle

- **생성**: `call_function` 또는 `eval_expression(store_as=...)` 호출 시 자동.
- **읽기**: `load_from_disk` 가 필요한 경우 자동 역직렬화.
- **삭제**: 명시적 `delete_variable`, LRU eviction, 세션 종료 시 cleanup hook.
- **세션 종료**: `backend/core/browser._finalize_disconnect` 가 `cleanup_namespace(client_id)` 호출 — memory dict 와 disk 파일 모두 정리.

---

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `APP_ALLOWED_LIBRARIES` | (없음) | 허용 라이브러리 루트 패키지 CSV. 예: `"sensordx,my_internal_lib"` |
| `APP_NAMESPACE_MEMORY_THRESHOLD` | `10485760` (10MB) | 이 크기(bytes) 미만이면 memory tier, 이상이면 disk spill |
| `APP_NAMESPACE_MAX_VARS` | `20` | 세션당 namespace 변수 총 상한. 초과 시 LRU 제거 |

---

## SKILL/AGENT frontmatter `api_refs` 필드

### 단일 함수 참조

```yaml
api_refs:
  - sensordx.utils.load_df
  - sensordx.analysis.compute_stats
```

### 모듈 와일드카드 (public 멤버 펼침)

```yaml
api_refs:
  - sensordx.utils      # public 함수/클래스 자동 펼침
```

- 한 모듈에서 최대 30 개까지 노출 (system prompt 폭증 방지).
- public 멤버만 (`_` 로 시작하는 이름은 제외).
- 같은 모듈에서 직접 정의된 함수/클래스만 (re-export 제외).

### 캐시 정책

- dev 모드: 모듈 `__file__` mtime 변경 시 자동 무효화 (핫리로드).
- frozen EXE: 1회 로드 후 영구 캐시 (재시작 전까지 변하지 않음).

---

## 자주 묻는 질문

### Q. `api_refs` 없이 `call_function` 만 호출하면 동작하는가?

기술적으로는 가능하지만 LLM 이 어떤 함수가 존재하는지 알지 못해 추측에 의존한다. SKILL/AGENT 에 `api_refs` 를 명시해 시그니처를 system prompt 에 노출하는 것이 정상 흐름.

### Q. essential API 를 부팅 시점부터 자동 노출하려면?

별도 PR 예정. 메타 도구 인프라 안정화 후 `APP_ESSENTIAL_APIS` CSV 와 동적 `register_tool` 래퍼로 구현 예정.

### Q. 세션 namespace 가 다른 사용자 세션과 섞일 가능성은?

없음. `client_id` 기준으로 격리된 dict 로 보관되고, disk 경로도 `client_id` 가 들어간 폴더 아래에만 생성된다.

### Q. namespace 변수가 너무 많아져 LLM 컨텍스트가 폭증하면?

`APP_NAMESPACE_MAX_VARS` 로 상한 조정. `list_namespace` 출력에 모든 변수가 나타나므로 한도가 너무 크면 LLM 응답이 느려질 수 있다.

---

## 관련 문서

- [skills.md](skills.md) — SKILL frontmatter 전체 필드
- [agents.md](agents.md) — AGENT frontmatter 전체 필드
- [builtin-tools.md](builtin-tools.md) — 7개 메타 도구 사양
- [.claude/rules/agent_extension.md](../.claude/rules/agent_extension.md) — register_tool 1:1 매핑 vs api_refs 메타 도구 패턴 선택 가이드
