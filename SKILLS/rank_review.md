---
name: rank_review
description: 순위가 매겨진 후보 데이터를 만들어 사람이 검토·선별하는 큐레이션 도구로 넘긴다
trigger:
  - 순위 검토
  - 후보 큐레이션
  - 검토 큐레이션
  - rank review
priority: 5
requires_tools:
  - exec_code
  - save_artifact
  - open_curation
---

# 순위 검토 큐레이션 핸드오프 가이드

분석으로 만든 **순위 후보 데이터**를 사람이 시각적으로 검토·선별하도록 큐레이션
도구(evaluator)로 넘기는 표준 절차다. 이 스킬의 책임은 후보 parquet 을 만들고
**마지막에 `open_curation` 을 한 번** 호출해 "큐레이션 도구 열기" 카드를 띄우는 데까지다.
실제 선별·재정렬·내보내기는 사람이 도구 안에서 한다 — 에이전트는 후보만 준비한다.

## 단계

1. **작업 계획 등록** — `add_todo` 로 2단계 plan 을 등록한다:
   `후보 데이터 산출` → `큐레이션 핸드오프`.

2. **후보 데이터 산출(parquet)** — `exec_code` 로 후보 표(polars DataFrame)를 만들고
   `save_artifact(kind="parquet")` 로 저장한다. 기간별·카테고리별로 나눠 **여러 개**
   저장해도 된다 — 다음 단계에서 경로를 모두 모아 한 번에 넘긴다.
   ```
   save_artifact(kind="parquet", filename="candidates.parquet", source="$cand_df")
   ```
   완료 후 `complete_todo` 로 1단계 마킹.

3. **큐레이션 핸드오프** — 만든 parquet 경로들을 모아 `open_curation` 을 **한 번만**
   호출한다. 컬럼 역할 매핑은 아래 표 그대로 넘긴다(도메인 고정값).
   ```
   open_curation(
     tool="evaluator",
     sources=["result/<session>/<ts>/candidates.parquet"],   # 여러 개면 리스트로 모두
     mapping={
       "select": "item_id",      # 좌측 리스트 항목의 고유 키
       "sort":   "rank",         # 리스트 정렬·내보내기 순위 재계산 기준(정수)
       "x":      "tkout_time",   # 본문 scatter x축(시간)
       "y":      "value",        # 본문 scatter y축(값)
       "legend": "category",     # scatter 시리즈 그룹(범례)
       "desc":   "item_desc"     # 리스트에 보조 표시할 설명
     }
   )
   ```
   `open_curation` 이 번들 스펙 작성·소스 경로 검증·패널 임베드를 모두 처리한다.
   호출 즉시 evaluator 가 채팅창 우측 패널에 iframe 으로 열려 번들의 parquet 들을 로드한다
   (패널 헤더 '최대화' 버튼으로 본문을 화면 전체로 키울 수 있다). 완료 후 `complete_todo` 로 2단계 마킹.

## 컬럼 역할 (매핑 계약)

`mapping` 의 **키**(select/sort/x/y/legend/desc)는 evaluator 가 해석하는 고정 역할이고,
**값**은 이 도메인의 실제 컬럼명이다.

| 역할 키 | 의미 | 이 도메인 컬럼 |
|---|---|---|
| `select` | 좌측 리스트 항목의 고유 키 | `item_id` |
| `sort` | 정렬·내보내기 순위(정수) | `rank` |
| `x` | 본문 scatter x축 | `tkout_time` |
| `y` | 본문 scatter y축 | `value` |
| `legend` | scatter 시리즈 그룹 | `category` |
| `desc` | 리스트 보조 설명 | `item_desc` |

> **다른 도메인은 이 SKILL 을 복사해 위 표의 값(컬럼명)만 자기 데이터에 맞게 바꾼다.**
> 역할 키는 절대 바꾸지 않는다. 컬럼이 관례명과 같으면 `mapping` 을 생략해도 evaluator
> 기본값이 적용된다(이 예시는 명시적으로 전부 적었다).

> **`legend` 는 다중 컬럼도 가능**하다 — 여러 차원을 합성한 그룹(예: `POR | A`)으로 보고
> 싶으면 리스트로 넘긴다: `"legend": ["category", "item_id"]`. **차트 종류·컬럼 매핑은 사용자가
> evaluator 안에서 직접 바꿀 수 있으므로**(scatter/line/bar/box/histogram/ecdf/heatmap + 매핑
> 설정 모달), SKILL 은 합리적 기본값만 넘기면 된다. 데이터 성격상 더 맞는 기본 차트가 있으면
> `open_curation(..., mark="bar")` 로 **기본 차트 종류**도 제안할 수 있다(선택, 생략 시 scatter).

## 주의

- `open_curation` 은 **맨 마지막에 한 번만** 호출한다. 후보를 다 만든 뒤 경로를 모아 넘긴다.
- 사람이 도구 안에서 소스를 더하거나 빼며 교정할 수 있으니, 미리 과하게 필터하지 말고
  **검토 후보를 넉넉히** 넘긴다.
- 선별 결과·통계를 응답 본문에 단정적으로 박지 않는다 — 최종 선별은 사람이 도구에서 확정한다.
