# evaluator 확장 심화

`extensions_architecture.md` 에서 분리. evaluator(`extensions/evaluator/`) 의 API 라우터 ·
ColumnMapping · 상태 사이드카 · export · 프론트 진입 · 차트 구현을 다룬다.

확장 시스템 공통(격리 원칙·로더·컨벤션·open_curation 규약) -> [extensions_architecture.md](extensions_architecture.md).

---

## 개요

AI Agent 가 만든 parquet 산출물을 **사람이 시각적으로 검토·선별·재정렬**해 최종 리포트용 데이터로
만드는 큐레이션 UI(Tableau 풍 BI 컨셉 차용). 좌측 선택 리스트(체크·순서 변경·너비 조절) + 본문
**차트 종류 셀렉터 + 매핑 설정 모달 + 차트 그리드**(다중 선택·페이지네이션·확대 라이트박스·
Filter/Legend) + 하단 저장/내보내기. 차트 종류는 메인 앱 `display_chart` 와 동일 **7종**(scatter/
line/bar/box/histogram/ecdf/heatmap)을 클라이언트에서 직접 렌더한다.

---

## API 라우터 (`backend/router.py`, prefix `/api/ext/evaluator`)

호스트 Origin 가드를 재사용한다(`dependencies=[Depends(require_local_origin)]`). 경로 해석은
`core.result_store.resolve_result_path` 로 일원화(RESULT_DIR 절대 기준 + containment).

| 엔드포인트 | 동작 |
|---|---|
| `GET /dataset?path=&select=&sort=&legend=&...` | 소스 parquet -> 선택 항목 리스트(`items`) + 차트 포인트(`points`) + `schema`([{name,dtype}], 매핑 UI 드롭다운용). `legend` 는 반복 쿼리 파라미터로 다중(`_legend_expr` 가 `" | "` 합성). x/y 는 빈 값이면 null |
| `GET /sources?path=` | 현재 소스가 속한 세션의 parquet 후보 목록(`<session>/_artifacts.jsonl` manifest 우선, 없으면 세션 폴더 디스크 스캔 폴백) - 소스 추가/변경 picker 카탈로그 |
| `GET /preview?path=&rows=10` | parquet head(N) + 스키마(NaN/inf·비원시 타입 JSON-safe) - picker 가 호스트 ArtifactData 와 동일한 형태의 미리보기 테이블을 그려 어떤 소스인지 보고 고르게 한다 |
| `GET /state?path=` | 저장된 큐레이션 상태(선택·순서·mark·mapping) 로드. 없거나 손상 시 빈 상태 폴백 |
| `POST /state {path, selected, order, mark, mapping}` | 큐레이션 상태를 소스 옆 사이드카에 저장 (저장하기) |
| `POST /export {path, selected, mapping, excluded, note}` | 선택 항목만 필터 + 차트 Filter 제외 행 실제 삭제 -> 새 parquet. 응답에 **큐레이션 요약** `summary{total, selected, dropped, excluded_rows, note}` 동봉 |

---

## ColumnMapping - 컬럼 역할

`mapping` 의 **키는 evaluator 가 해석하는 고정 역할**, 값은 도메인 실제 컬럼명.
역할은 **공통**(차트 무관)과 **차트별**(mark 가변)로 나뉜다.

| 역할 키 | 군 | 의미 | 기본값 |
|---|---|---|---|
| `select` | 공통 | 좌측 리스트 항목의 고유 키 | `item_id` |
| `sort` | 공통 | 정렬·내보내기 순위(정수, export 시 재계산 대상) | `rank` |
| `legend` | 공통 | 시리즈 그룹(범례) - **다중 컬럼 허용**(`list[str]`, `" | "` 합성) | `["category"]` |
| `desc` | 공통 | 리스트 보조 설명 (**선택적** - 컬럼 부재 시 desc=None 폴백) | `item_desc` |
| `x` | 차트별 | 차트 가로축 (scatter/line/bar/histogram/ecdf/heatmap) | `tkout_time` |
| `y` | 차트별 | 차트 세로축 (scatter/line/bar/box/heatmap) | `value` |

> `legend` 는 `list[str]` 이다. `x`/`y` 는 빈 문자열이면 '미매핑'으로 취급해 `required_columns()`
> 에서 제외한다(histogram 은 x 만, box 는 y 만 쓰므로). `ColumnMapping` 은 `extra="ignore"` 라
> 프론트가 차트 옵션(`mark`·`aggregate`)을 같은 매핑 객체에 실어 보내도 export 검증을 깨지 않는다.

---

## 상태 사이드카 · export 규칙

- **상태 사이드카** `<stem>.evaluator-state.json` - 소스 parquet 과 같은 폴더에 형제로 저장
  (`selected` 키 목록 + `order` 전체 순서 + `mark` 차트 종류 + `mapping` 컬럼 매핑 오버라이드).
  재진입 시 `selected`/`order` 는 현재 아이템 집합과 정확히 일치할 때만 복원하고, `mark`/`mapping`
  은 있으면 번들/쿼리 기본값보다 우선한다(사용자가 도구 안에서 바꾼 차트 설정 영속). `mapping` 은
  데이터 투영을 바꾸므로 `loadActiveSource` 가 **상태를 먼저 읽고** 그 매핑으로 `/dataset` 을 요청한다.

- **export 정수 재계산**: `selected` 가 곧 최종 리스트 순서이며, 그 순서대로 sort 컬럼을 1..N 정수로
  덮어쓴다(같은 선택키의 모든 행이 동일 정수). 결과는 `<stem>.curated.parquet` 으로 쓴다.

- **차트 Filter 제외 반영(데이터에 실제 삭제)**: `excluded`(선택키별 0-based point 인덱스)의 행을
  최종 parquet 에서 **실제로 제거**한다. 프론트 `pointsByKey` 인덱스와 정합하도록 백엔드가
  `pl.int_range(0, pl.len()).over(key)` 로 키별 행 순번 `__pos__` 를 만들어 `(key, pos)` anti-join
  으로 빼낸다(`_apply_point_exclusions`). 남는 행이 0이면 422.

- **세션 manifest 기록**: export 시 산출물을 **세션 루트** `_artifacts.jsonl` 에 best-effort append.
  채팅 에이전트의 산출물 재발견(`read_manifest_entries`)이 큐레이션 결과도 보게 한다. 호스트 private
  상수에 의존하지 않으려고 `_MANIFEST_FILENAME` 을 **의도적으로 복제**(호스트 리팩토링에 격리).

- **메인 앱 실시간 인폼(export-back)**: 내보내기 성공 시 프론트가
  `BroadcastChannel("evaluator:exports")` 로 `{type:"export", session, path, filename, rows, columns, summary}` 를 post. 같은 출처인 메인 앱 탭의 `frontend/src/lib/evaluatorBridge.svelte.js` 가 구독해,
  그 세션의 **마지막 어시스턴트 메시지에 parquet 데이터 칩**을 붙이고 localStorage 영속시킨다
  (재내보내기 시 `_refreshSummary` 로 같은 경로 칩의 요약 갱신). 칩이 메시지에 임베드되므로
  새로고침 후에도 남는다. 별도 탭이므로 채팅 SSE 가 아닌 BroadcastChannel 을 쓴다.
  - **칩 요약 + 1클릭 후속**: `ArtifactData.svelte` 가 `payload.summary` 를 요약 배너(후보 N개 중
    M개 선택·X행 제외·메모)로 띄우고, **"이어서 작업"** 버튼이 `artifactActions.seedCurationFollowup`
    으로 결정 맥락 머리말 + 큐레이션 경로 pill 을 컴포저에 시드한다(기존 `ui.composerSetParts` 신호
    재사용 - 사람의 판단이 에이전트에게 환류됨).

---

## 프론트 진입 (`frontend/src/App.svelte`)

URL 쿼리로 데이터 소스를 받는다. `onMount` 에서 읽어 데이터셋·상태를 로드한다.

| 진입 | 의미 |
|---|---|
| `?path=result/<session>/<ts>/x.parquet` | 단일 소스 직접 지정 (`&legend=a&legend=b` 다중 가능) |
| `?bundle=result/.../<tool>.bundle.json` | 다중 소스 contract(`open_curation` 산출). 번들을 fetch 해 `sources`·`mapping`·선택적 `mark` 확정 - `path` 보다 우선 |
| (둘 다 없음) | **랜딩 페이지**(`landing`) - 안내 메시지 + `result/...parquet` 경로 입력. 패널 런처로 소스 없이 열릴 때 |

- **다중 소스 = 소스 탭**: 성격 다른 후보군 전제라 **병합하지 않고** 소스마다 탭으로 한 번에 하나씩
  큐레이션한다(각 탭은 단일 소스 엔드포인트 재사용, 탭 전환 시 선택·순서·매핑·mark·schema 를 stash 에 보존·복원). 단일 소스면 탭바를 숨긴다.
- **차트 종류 셀렉터 + 매핑 설정 모달**: 본문 상단 세그먼트로 차트 종류(7종)를 바꾸고(데이터 재요청
  없이 재렌더만), 매핑 설정 모달에서 역할별 **설명 + 컬럼 드롭다운**으로 매핑한다. legend 는 컬럼 토글 칩 **다중 선택**(순서=합성 순서). 컬럼 역할이 바뀌면 `/dataset` 을 재요청하되 **선택키 집합이 그대로면 사용자의 선택·순서를 보존**한다(`applyMappingConfig`).
- **소스 교정 picker**: `GET /sources` 카탈로그 + `GET /preview` head(10) 미리보기(좌측 후보 리스트 +
  우측 미리보기 테이블의 마스터-디테일)로 **추가**(새 탭)·**제거**(탭 x)·**변경**(단일 소스 전용 교체)한다.
- **좌측 패널 너비 조절**: 사이드바 우측 경계 `.col-resizer` 를 pointer 드래그(`sidebarWidth` clamp 220-640). **진입 시 전부 체크(선택)** 가 기본 - 사이드카가 있으면 그대로 복원한다.
- **리스트 검색·필터·일괄 선택**: 검색(key·desc 부분일치)·legend 필터(`legendByKey` 합집합 드롭다운)로 `filteredOrder`(가시 순서)를 좁힌다. 일괄 버튼은 **포함**(`includeDisplayed`)·**제외**(`excludeDisplayed`) 두 개로, **차트로 표시 선택한 항목(`displaySelection`)**을 내보내기 선택(체크)에 더하거나 뺀다(표시 선택이 없으면 비활성). 과거 전체/해제/반전(가시 집합 대상)은 폐지.
- **순서 변경 = 드래그&드롭**: 행을 `draggable` 로 끌어 다른 행 위에 놓으면 순서를 재배치한다(`onItemDrop`). 필터가 걸려 중간에 숨은 항목이 있어도 항상 전체 order 기준으로 정합한다.
- **병합 보기(merge)**: 표시 선택(`displaySelection`)된 차트들의 points 를 `mergePoints(pointsByKey, order intersect displaySelection)` 로 단순 결합해 단일 standalone `ChartCell`(읽기전용)로 렌더한다. **legend 를 항목 키로 덮어쓰지 않고 원래 legend 매핑을 보존**한다.
- **표시 선택**: 단일 클릭·Ctrl/Command+클릭 토글·**Shift+클릭 범위**(`displayAnchor` 기준). 전체 보기/보기 해제 버튼이 `displaySelection` 을 가시 집합 전체/빈 값으로 설정한다.

---

## 차트 그리드·라이트박스 (클라이언트 사이드)

본문은 메인 앱 `display_chart` 의 UX 를 **클라이언트에서 자체 구현**한다 - points 가 `/dataset` 으로
이미 적재돼 있고, 차트 상호작용은 클라이언트 상태라 격리 원칙상 메인 앱의 spec->render->`/api/chart/filter`
파이프라인에 결합하지 않는다. **Filter 제외는 내보내기 시 데이터에 반영**(export `excluded` 로 전송 ->
백엔드가 실제 행 삭제)되고, 레전드 순서·색상·Hide 는 **시각 전용**(선택/순서/export 에 무영향)이다.

| 파일 | 역할 |
|---|---|
| `lib/chartOption.js` | **mark 별 빌더 디스패처** `buildChartOption(mark, points, snapshot, opts)` -> 7종 ECharts option. 제외·레전드(순서·색상·Hide) 반영 + brush 환원용 `row_ids` + `brushable` 플래그 + 매핑 누락 시 친절한 `error`. **brushable 차트(scatter/line/ecdf)는 option 에 `brush` 컴포넌트를 포함**해야 라이트박스의 `takeGlobalCursor(key:"brush")` 가 박스 선택을 활성화한다(메인 앱 `render_spec_to_echarts` 의 `"brush": {}` 와 동일 역할). line/ecdf 는 투명 scatter overlay 로 brush 우회. box/histogram/ecdf 통계는 JS 로 계산(메인 앱 알고리즘과 동치 - 분위수 선형보간·10빈·누적비율). `mergePoints(pointsByKey, keys)` 는 병합 보기용 결합(legend 보존). `MARKS`/`MARK_BY_ID`/`AGGREGATES` 메타데이터를 매핑 UI 와 공유 |
| `lib/chartState.svelte.js` | 선택키별 `{stack:[snapshot], cursor}` undo/redo 스토어. snapshot = `{excluded:number[], legend:{order,colors,hidden}}`. 그리드·라이트박스가 같은 스토어를 봐 동시 재렌더 |
| `lib/ChartCell.svelte` | 단일 ECharts. `mark`·`roles`·`aggregate` props 로 빌더 분기. 매핑 누락 시 안내 문구. **embedded 셀은 `brush` 컴포넌트를 제거(`renderOption`)** 해 클릭=확대 전용으로 두고, standalone 은 brush 를 유지하고 `onchart(chart, row_ids)` 로 라이트박스에 통지. **다크/라이트는 `makeEchartsTheme()`(CSS 변수 → 축/텍스트/그리드 색)을 `echarts.init` 에 주입**하고, `themeState.name`(`lib/theme.svelte.js`) 변경 시 dispose 후 재init |
| `lib/ChartGrid.svelte` | 제목 패널 + 페이지당 12개 페이지네이션. `mark`/`roles`/`aggregate` 를 셀에 전달. 셀 클릭 -> 라이트박스 |
| `lib/ChartLightbox.svelte` | 리사이즈 확대 모달 + Filter/Filter All/Reset/Undo/Redo + 레전드 편집 패널. brush 는 `brushable` 차트에서만 활성. **인라인 SVG 아이콘**(오프라인-퍼스트라 메인 앱의 Material Symbols CDN 미사용) |

- **Filter 의미**: brush 점 또는 레전드 그룹 선택 -> 해당 점/그룹을 제외. *Filter All* 은 표시 중인 모든 차트에 제외. Reset/Undo/Redo 는 현재 차트 키의 스택만 조작. **이 제외(`snapshot.excluded`)는 내보내기 시 선택키별로 모여 export `excluded` 로 전송돼 최종 parquet 에서 실제 행이 삭제된다**(`App.svelte` `collectExclusions`).
- **chartState 식별자**: `${activePath}::${key}` 로 네임스페이스해 소스 간 같은 키가 필터 상태를 공유하지 않게 한다.

---

## SKILL 작성 예시 (`SKILLS/rank_review.md`)

큐레이션 핸드오프를 따르는 SKILL 작성 표준. `requires_tools: [exec_code, save_artifact, open_curation]`,
2단계 plan(`후보 데이터 산출` -> `큐레이션 핸드오프`), **마지막에 `open_curation` 을 한 번만** 호출.
`mapping` 의 역할 키는 고정, 값(컬럼명)만 도메인에 맞게 바꿔 복사한다.

새 도메인 적용: 이 SKILL 을 복사해 매핑 표의 값만 교체. 역할 키는 절대 바꾸지 않는다.

---

## Mock 검증 (시나리오 H)

트리거: `순위 검토`·`후보 큐레이션`·`큐레이션 도구`.
`exec_code`(후보) -> `save_artifact`(parquet) -> `open_curation` 핸드오프 흐름을 실 LLM 없이 검증한다.
진입 카드 markdown 칩 렌더 + `/ext/evaluator/?bundle=` iframe 자동 임베드가 `rank_review` SKILL 의
핸드오프 계약과 동일한지 확인한다.
