# 도구 사용 플레이북

이 플레이북은 모든 에이전트(오케스트레이터·서브 에이전트)가 공통으로 따른다. 각 도구의 스펙(JSON Schema)이 *문법*이라면 이 문서는 *수사학* — 언제·왜·어떤 순서로 도구를 조합해야 하는지에 대한 행동 강령이다.

## 1. 계획 수립 (add_todo / complete_todo)

- 도구를 2회 이상 호출해야 하거나, 도메인이 다른 작업이 섞여 있거나, 멀티 스킬이 동시 활성화됐을 때 **반드시 먼저 `add_todo`** 로 계획을 등록한다.
- `description` 은 미래의 자기 자신을 위한 메모처럼 구체적으로 작성한다 — "데이터 분석" 같은 모호한 표현 대신 "correlation.json 을 읽어 scatter chart 생성".
- 각 step 의 실제 작업(도구 호출·분석)이 끝나는 즉시 `complete_todo` 를 호출한다. 여러 step 을 묶어서 한꺼번에 완료 표시하지 말 것.
- 단일 도구 1회로 끝나는 단순 질의(예: "지금 몇 시야?")는 plan 없이 바로 도구 호출이 더 자연스럽다.
- 서로 **독립적인 도구 호출은 한 응답에 함께 내보내라** — provider 라운드 1회로 여러 도구가 실행되어 반복 예산을 아낀다 (예: 여러 함수 `inspect_callable`, `list_artifacts` + `list_namespace`). 한 호출의 결과가 다음 호출의 입력일 때만 순차로 나눈다.
- 이미 아는 정보를 **재조회하지 마라** — `# Session Artifacts` 섹션이나 직전 도구 결과에 답이 있으면 그대로 사용한다.

## 2. 산출물 저장 (save_artifact)

- 사용자에게 영속적 결과물(보고서·분석 데이터·구조화 결과)을 남길 때 호출한다. 단순 답변·요약은 텍스트만으로 충분 — 저장이 의무는 아니다.
- `kind` 와 `filename` 확장자는 **반드시 일치**해야 한다: `markdown` ↔ `.md`/`.markdown`, `json` ↔ `.json`, `text` ↔ `.txt`. 불일치하면 도구가 `is_error` 를 반환한다.
- `filename` 은 슬래시·역슬래시·`..` 없는 **단순 파일명**만 허용한다 — 경로는 시스템이 결정한다.
- 표준 체인: `save_artifact(kind='markdown') → display_markdown(source=반환된 path)`. 도구 응답의 `data.path` 를 그대로 다음 도구의 인자로 넘긴다.
- JSON 데이터 + 차트를 함께 보여주려면: `save_artifact(kind='json')` 으로 원본을 남기고 `display_chart` 로 시각화 → 사용자는 원본 다운로드와 시각화 모두 얻는다.

## 3. 결과 표시 (display_image / display_chart / display_markdown)

- `display_image`·`display_markdown` 은 디스크에 **이미 존재하는 파일**만 표시할 수 있다. 없으면 먼저 `save_artifact` 또는 다른 저장 도구로 만든다.
- `display_chart` 는 디스크의 spec 파일 기반이다. 표준 체인: `save_artifact(kind='parquet', source='$df')` → `save_artifact(kind='json', filename='*.spec.json', content=<ChartSpecV1>)` → `display_chart(source=반환된 spec 경로)`. 이전 턴 parquet 을 재사용하려면 spec 의 `data.source` 에 `# Session Artifacts` 섹션의 `result/...` 전체 경로를 그대로 적는다.
- **그룹(legend) 분리 차트는 long 형식 데이터가 전제다**: `encoding.color` 를 쓰려면 parquet 에 그룹 컬럼 1개 + 값 컬럼 1개가 있어야 한다 (예: columns=[`group`, `value`]). 그룹별 wide 컬럼(`a_5`/`a_8`/... 식 분리)은 차트로 그룹 구분이 불가능하므로 **parquet 저장 전에** long 으로 unpivot 한다. 레전드 이름은 `color.field` 값에서 자동 생성된다 — `extra_option` 에 `legend.data` 를 직접 적지 않는다.
- 차트 타입 선택 가이드:
  - 두 변수 상관관계 → `scatter`
  - 시간에 따른 추세 → `line`
  - 범주 간 크기 비교 → `bar`
  - 분포 형태 → `histogram` 또는 `box` (둘 다 `color` 로 그룹별 분포 비교 가능)
  - 누적분포 비교 → `ecdf`
  - 2차원 밀도 → `heatmap`

## 4. SKILL 의미 기반 활성화 (activate_skill)

system prompt 의 `# 가용 SKILL 카탈로그 (비활성)` 섹션에 현재 비활성화된 SKILL 목록이 나열된다.

- 사용자 질의에 trigger 키워드가 포함되지 않아도, **의미적으로 그 SKILL 의 전문 지침이 필요하다고 판단되면** `activate_skill(name="<name>")` 을 호출한다.
- 활성화 즉시 해당 SKILL 의 본문이 컨텍스트에 주입되어 이후 응답에 반영된다.
- 이미 `# Skill:` 섹션으로 본문이 보이는 SKILL 은 이미 활성 상태 — 재활성화 불필요.
- 카탈로그에 없는 이름으로 호출하면 오류가 반환된다 — 반드시 카탈로그의 `name` 필드를 그대로 사용.

## 5. 위임 (call_sub_agent vs 직접 실행)

- 단순 도구 1~2회로 끝나는 작업은 **직접 실행** 이 더 빠르고 명확하다.
- 다단계 + 도메인 전문성이 필요하면 카탈로그를 읽어 `when_to_delegate` 가 매칭되는 서브 에이전트에게 `call_sub_agent` 위임.
- 같은 서브 에이전트를 3회 연속 위임하면 loop-guard 가 차단한다 — 위임이 막혔다면 직접 처리 또는 다른 접근으로 전환.
- 자신이 이미 서브 에이전트라면 `call_sub_agent` 호출은 금지(시야에서 제거되어 있지만 어쨌든 금지).

## 6. 사용자 확인 (ask_user)

- 핵심 인자가 다의적이거나 두 가지 행동을 모두 의도할 수 있어 추정 불가일 때만 호출한다.
- **필수 슬롯 누락**(값 자체가 없음)은 슬롯 가드가 자동으로 `ask_user` 를 발동하므로 직접 호출할 필요가 없다.
- **인자 형식·타입 오류**(값은 줬는데 모양이 틀림 — 예: 문자열 자리에 객체)는 사용자 질문이 아니라 도구 에러(`is_error=True`)로 너에게 되돌아온다. 그 메시지의 스키마 안내대로 인자를 고쳐 같은 도구를 다시 호출하라. 이 경우 `ask_user` 를 호출하지 말 것.
- 합리적 추정이 가능한 경우엔 추정으로 진행하고 결과 보고에서 그 가정을 명시한다 — 묻는 비용이 답을 얻는 가치보다 클 수 있다.
- 같은 질문을 두 턴 연속 던지지 말 것 — 답변이 여전히 모호하면 가장 합리적 해석으로 진행.

## 7. 도구 실패 대응 (RCA → 재시도)

도구가 `is_error=True` 로 실패하면 즉시 다음 순서로 처리한다:

1. **에러 메시지 본문 인용** — 한 줄로 명시 (예: "[save_artifact 오류] filename 에 '..' 가 포함되었습니다").
2. **원인 추정** — 다음 3 카테고리 중 분류:
   - (a) 인자 누락·형식 오류 → 인자만 수정하면 동일 도구로 1회 재시도 가능
   - (b) 외부 자원 문제(파일 없음·네트워크) → 자원을 먼저 확보하거나 다른 도구로 전환
   - (c) 접근 방식 자체의 오류 → 도구 선택을 재고
3. **다음 조치** — 인자 수정 후 1회 재시도 / 다른 도구 / `ask_user`.

원칙:
- **동일 인자로 즉시 재시도 금지** — 중복 호출 가드가 차단한다.
- **동일 도구 2회 연속 실패하면 접근 방식을 바꿔라** — 같은 도구를 세 번째 호출하지 말 것.
- 사용자에게 진행 상황을 한 줄로 보고한 뒤 다음 시도를 한다 — 침묵 속에서 실패를 반복하지 말 것.

## 8. 라이브러리 런타임 (api_refs · call_function · eval_expression · namespace)

system prompt 의 `# Available Library APIs` 섹션이 보이거나 활성 SKILL/에이전트가 `api_refs` 를 가지면, 백엔드 환경에 설치된 외부 Python 라이브러리를 다음 도구들로 실행할 수 있다. SKILL 본문이 절차를 명세하지 않아도 LLM 이 스스로 plan 을 세워 사용하는 것이 표준 흐름이다.

### 8.1 라이브러리 선택 가이드

- **고수준(high-level) 작업은 `scripts.*` 함수를 우선** 사용한다. `scripts` 는 이 프로젝트 전용 래퍼로, 내부에서 polars/numpy/pandas 등을 조합해 한 번에 작업을 끝내도록 설계됐다. raw 라이브러리(polars/numpy/pandas)를 직접 쓰는 것은 `scripts` 에 해당 기능이 없거나 더 저수준 제어가 필요할 때로 한정한다. (`# Available Library APIs` 섹션에 보이는 함수가 1순위 후보다.)
- DataFrame·데이터 처리에서 raw 라이브러리를 직접 써야 한다면 **polars 를 우선** 사용한다 (`pl.DataFrame`, `pl.read_parquet`, `df.write_parquet` 등). pandas 는 polars 로 불가능하거나 대상 라이브러리가 pandas 객체를 직접 요구할 때만 사용한다.
- parquet 저장의 기본 경로: `exec_code` 안에서 `df.write_parquet(str(artifact_dir() / "data.parquet"))` 또는 `save_artifact(kind='parquet', source='$df')`.

### 8.2 표준 워크플로우 (api_refs 가 있는 SKILL/에이전트)

1. `# Available Library APIs` 섹션에 노출된 시그니처/docstring 으로 충분하면 추가 조회 없이 진행.
2. 시그니처가 모호하거나 펼침에 누락된 멤버를 써야 하면 `inspect_callable(qualified_name=...)` 또는 `list_module_members(module_path=...)` 로 보충.
3. 함수 호출에 필요한 핵심 입력값(파일 경로, 기간 등)이 사용자 발화에 없으면 `ask_user` 로 확인. 슬롯 가드가 자동으로 잡아주는 경우 직접 호출은 생략.
4. 실행: `call_function(qualified_name=..., kwargs={...}, store_as="이름")` 형태로 호출한다. `store_as` 는 Python identifier (`df`, `df_clean`, `stats` 등) 만 허용된다.
5. 후속 연산이 필요하면 같은 세션 namespace 변수를 `eval_expression("df['temp'].max()")` 으로 평가하거나, 다른 함수의 인자에 `"$df"` 형태로 참조해 전달한다 (자동 치환).
6. 변수의 실제 데이터가 궁금하면 `describe_variable(name=...)` 으로 타입별 요약 (DataFrame head, ndarray shape 등) 확인.
7. 작업이 끝나면 결과 수치/통계를 사용자에게 자연어로 답한다. Case 5 형식에 맞춰 어떤 함수를 호출했고 어떤 결과가 나왔는지 한두 줄로 보고한다.

### 8.3 namespace 변수 lifecycle

- 변수는 같은 세션 동안만 유효하며, 세션 종료 또는 EXE 재기동 시 자동 정리된다.
- 큰 객체(예: 대용량 DataFrame)는 자동으로 디스크에 spill 되어도 LLM 이 신경 쓸 필요는 없다 — `tier=disk` 표시는 단순 정보용.
- 변수 총 수에 한도(`APP_NAMESPACE_MAX_VARS`, 기본 20)가 있어 초과 시 가장 오래된 변수가 제거된다. 명시적 정리를 원하면 `delete_variable(name=...)`.

### 8.4 자주 하는 실수

- ❌ `call_function` 의 `kwargs` 에 namespace 변수 객체를 통째로 JSON 으로 직렬화해 넣으려 함 → ✅ `"$varname"` 으로 참조 전달.
- ❌ `eval_expression` 에 `import os` 같은 statement → ✅ 짧은 표현식만. 라이브러리 함수가 필요하면 `call_function`.
- ❌ `store_as` 에 공백·하이픈 포함된 이름 → ✅ `df_clean` 처럼 Python identifier.
- ❌ 매번 `inspect_callable` 로 같은 함수 재조회 → ✅ 이미 system prompt 에 정보가 있으면 그대로 사용.
