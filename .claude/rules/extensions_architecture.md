# 확장 시스템 (Extensions) 아키텍처

`extensions/` 는 **메인 앱과 완전히 격리된 독립 도구**(Svelte 5 SPA + FastAPI 라우터)를 담는다.
호스트는 개별 도구를 모르고 **컨벤션**(`<tool>/backend/router.py` 의 `get_router()` +
`<tool>/frontend/dist`)만 따른다. 따라서 폴더 단위로 추가·삭제할 수 있고 host 코드 변경이 필요 없다.

예시: [evaluator](../../extensions/evaluator/) — parquet 큐레이션 UI.

---

## 격리 원칙 (필독)

| 보장 | 근거 |
|---|---|
| 폴더 하나를 통째로 지워도 host 무영향 | 로더가 빈손이면 no-op, App.spec 글롭이 빈 리스트, `open_curation` 은 SKILL 이 호출 안 함 |
| 새 도구 추가에 host 코드 수정 불필요 | 로더가 컨벤션으로 자동 발견·마운트 |
| 한 확장의 실패가 부팅을 막지 않음 | 로더가 확장별 `try/except` 로 격리(경고 로그 후 다음 확장) |
| 확장 1개 실패가 EXE 빌드를 막지 않음 | `App.spec` 이 폴더 존재 여부만 보고 선별 번들 |

> 확장 모듈은 **패키지-상대 import 를 쓰지 않는다.** 파일 경로로 적재되므로(`spec_from_file_location`,
> flat 모듈명) `core.*`·`api.*`·polars·fastapi 처럼 **호스트가 이미 번들한 절대 import 만** 사용한다.

---

## 디렉터리 컨벤션

```
extensions/<tool>/
  backend/
    router.py          ← get_router() -> APIRouter (prefix="/api/ext/<tool>")
    tests/             ← 확장 자체 테스트 (번들 제외)
  frontend/
    src/ ...           ← Svelte5 SPA 소스 (번들 제외)
    dist/              ← npm run build 산출물 (정적 서빙 대상 — 번들 포함)
  README.md
```

| 컨벤션 경로 | 역할 | 마운트 |
|---|---|---|
| `<tool>/backend/router.py` `get_router()` | API 라우터 팩토리 (`APIRouter` 반환) | `/api/ext/<tool>` |
| `<tool>/frontend/dist` | 빌드된 SPA(`html=True`) | `/ext/<tool>` |

둘 다 **있는 것만** 마운트된다(라우터만·정적만 있어도 동작). `_`/`.` 접두 폴더는 내부용으로 스캔에서 제외.

---

## 로더 (`backend/core/extensions_loader.py`)

`load_extensions(app)` 가 `extensions/*/` 를 스캔해 각 도구의 라우터·정적 SPA 를 마운트한다.

- **경로 단일 진실원천**: `_extensions_dir()` = `_project_root() / "extensions"` — frozen 은
  `MEIPASS/extensions`, dev 는 `PROJECT_ROOT/extensions` (`core.config._project_root` 분기 재사용).
- **파일 경로 적재로 frozen 대응**: 라우터 모듈을 name-import 가 아니라
  `importlib.util.spec_from_file_location(f"ext_{name}_router", router_py)` 로 **flat(점 없는)
  모듈명**으로 적재한다. PyInstaller onefile 이 datas 를 `MEIPASS` 디스크로 추출하므로 `router.py`
  를 파일에서 읽어 실행할 수 있고, flat 모듈명이라 패키지-상대 import 부재 문제를 피한다.
- **확장별 격리**: `_mount_extension` 호출을 `try/except Exception` 으로 감싸 한 확장의 로드 실패가
  앱 전체 부팅을 막지 않게 한다(`logger.warning` 후 다음 확장 진행).
- **`get_router()` 검증**: 팩토리 미정의·`APIRouter` 아닌 반환은 경고 후 건너뛴다(부팅 계속).
- **`extensions/` 부재 시 즉시 return** → no-op.

### main.py 호출 순서 (중요)

```python
# backend/main.py
app.include_router(api_router)          # /api/*
...
load_extensions(app)                    # /api/ext/<name>, /ext/<name>
if WEB_DIR.exists():
    @app.get("/{path:path}")           # SPA catch-all 폴백
    async def spa_router(path): ...
```

> Starlette 는 등록 **순서**로 라우트를 매칭한다. `load_extensions(app)` 는 반드시 메인 SPA
> catch-all(`/{path:path}`) **보다 먼저** 호출돼야 `/api/ext/*`·`/ext/*` 가 폴백에 잡히지 않는다.

---

## 빌드 번들링 (`packaging/App.spec`)

`App.spec` 이 빌드 시 `extensions/*` 를 글롭해 **런타임에 필요한 부분만 선별 번들**한다.

| 포함 | 제외 |
|---|---|
| `<tool>/backend` → `MEIPASS/extensions/<tool>/backend` | `node_modules` · `frontend/src` · `tests` (EXE 비대화 방지) |
| `<tool>/frontend/dist` → `MEIPASS/extensions/<tool>/frontend/dist` | |

- 폴더(`backend`·`dist`)가 **있을 때만** `datas` 에 추가 — 없거나 비면 빈 리스트 → **no-op**.
- 확장 1개 폴더를 지워도 spec 수정 없이 다음 빌드에 자동 반영(삭제 = 미수집).
- 로더가 런타임에 파일 경로로 적재하므로 `collect_submodules`/`hiddenimports` 가 **불필요**하다
  (메인 백엔드처럼 정적 import 그래프에 들어가지 않음).

> **`frontend/dist` 는 `release.ps1` 이 App.spec 보다 먼저 빌드한다.** App.spec 은 dist 가 "있을
> 때만" 번들하므로, 빌드를 안 하면 stale/누락 dist 가 박힌다. `release.ps1` 이 `extensions/*/frontend`
> 를 폴더 컨벤션으로 자동 발견해 `npm ci/install`(node_modules 부재 시) + `npm run build` 한다 —
> 한 확장의 빌드 실패는 경고 후 계속(격리). 상세 → `update_architecture.md`.

---

## 진입 규약 — `open_curation` (`backend/agent/tools/curation.py`)

에이전트가 후보 parquet 을 만든 뒤 `open_curation(tool, sources, mapping, mark, title)` 를 **한 번** 호출하면:

1. `tool` 이름 검증(`^[a-z0-9][a-z0-9_-]*$` — `/ext/<tool>/` 경로 세그먼트로 안전) ·
   `sources` 검증(`resolve_result_path` containment + parquet 확장자) · `mapping` 검증(평탄한
   `{str: str | list[str]}` — legend 등 다중 컬럼 역할을 위해 리스트 값 허용).
2. 번들 스펙 `<tool>.bundle.json`(`{tool, sources, mapping}` + 선택적 `mark`)을 **현재 턴 슬롯**에 쓴다.
   `mark`(기본 차트 종류)는 호스트가 해석하지 않는 **제네릭 통과값** — 비어있으면 키 자체를 생략하고
   확장이 해석한다(evaluator 는 `MARK_BY_ID` 로 검증, 미지정 시 scatter).
3. `ToolResult(data={"kind": "extension", "tool", "src", "title", "bundle"})` 를 반환한다 —
   `src` 는 `/ext/<tool>/?bundle=<URL인코딩 result 경로>`. 프론트는 이 칩을 **우측 아티팩트
   패널에 확장 SPA 를 same-origin iframe 으로 임베드**하는 `ArtifactExtension.svelte` 로 렌더하고
   자동으로 연다(새 탭 아님). iframe 안에서 확장이 번들의 parquet 들을 로드한다.

| 항목 | 처리 |
|---|---|
| extension 칩 인식 | 프론트 `chatActions.svelte.js` 의 `_ARTIFACT_TOOL_NAMES` 에 `open_curation`, `_ARTIFACT_KINDS` 에 `extension` 등록 → 칩 자동 생성·패널 자동 오픈 |
| 패널 iframe 임베드 | `ArtifactPanel` 의 kind 분기가 `ArtifactExtension` 로 `<iframe src=payload.src>` 렌더. evaluator `vite base="/ext/evaluator/"` 라 iframe 내 에셋·`/api/ext` 호출이 same-origin → Origin 가드 통과 |
| '새 탭' 버튼 | `ArtifactExtension` 헤더의 버튼이 `window.open(payload.src, "_blank", "noopener,noreferrer")` 로 별도 창에서도 연다(`display_markdown` 패널과 동일 패턴) |
| 영속 | 칩이 메시지(`artifactChips`)에 임베드되어 localStorage 로 영속 — 세션 재진입 후에도 같은 번들로 iframe 복원 |
| evaluator 비특정(제네릭) | `tool` 인자로 임의 확장을 가리키고 `mapping` 도 해석 없이 번들에 그대로 실어 보낸다(확장이 해석). 확장 진입 규약을 한 곳에 모은 호스트 훅 |
| 폴더 삭제 시 | SKILL 이 `open_curation` 을 호출하지 않으므로 무해(no-op) |

> iframe 임베드로 여는 이유: 데스크탑 앱은 채팅이 곧 전체 창이라 같은 탭 이동 시 세션이 소실되고,
> 새 탭은 맥락을 끊는다. same-origin iframe 은 격리된 빌드 SPA 를 그대로 재사용하면서 패널 안에서
> 보게 한다(`ArtifactExtension`). 별도 창이 필요하면 헤더 '새 탭' 버튼을 쓴다.

## 패널 런처 드롭다운 + `extension.json` (`backend/core/extensions_loader.py`, `backend/api/extensions.py`)

TopBar 패널-열기 버튼 옆 caret(`ExtensionMenu.svelte`)이 **사용 가능한 확장**을 띄운다. 부팅 시
`GET /api/extensions`(=`list_available_extensions()`)를 1회 받아 `ui.extensions` 에 캐시한다.

- `frontend/dist` 가 있는(=화면이 있는) 확장만 반환한다 — 라우터만 있는 확장은 런처에 없다.
- 각 항목 `{tool, name, description, icon}` 의 표시 이름·설명은 확장 루트의 선택적
  `extension.json`(`{name, description, icon}`)에서 오고, 없으면 폴더명으로 폴백한다.
- 런처로 연 확장은 `openExtensionPanel(tool)` 이 **휘발 뷰**(`ui.extensionView`, 메시지 칩과 별개)를
  만들어 `/ext/<tool>/`(쿼리 없음=랜딩)로 임베드한다. open_curation 칩은 영속, 런처 뷰는 휘발.
- `extension.json` 은 App.spec 이 확장 글롭에서 `(<ext>/extension.json, extensions/<name>)` 로 번들해
  frozen 에서도 enumeration 이 동작한다.

> 확장 SPA 는 `?path=`·`?bundle=` 가 **없을 때** 깨지지 않는 **랜딩 페이지**(소스 경로 입력 안내)를
> 갖춰야 한다 — 런처로 소스 없이 열릴 수 있기 때문. evaluator 는 `App.svelte` 의 `landing` 분기로
> 안내 메시지 + `result/…parquet` 경로 입력을 제공한다.

---

## 예시 확장: evaluator (`extensions/evaluator/`)

AI Agent 가 만든 parquet 산출물을 **사람이 시각적으로 검토·선별·재정렬**해 최종 리포트용 데이터로
만드는 큐레이션 UI(Tableau 풍 BI 컨셉 차용). 좌측 선택 리스트(체크·순서 변경·**너비 조절**) + 본문
**차트 종류 셀렉터 + 매핑 설정 모달 + 차트 그리드**(다중 선택·페이지네이션·확대 라이트박스·
Filter/Legend) + 하단 저장/내보내기. 차트 종류는 메인 앱 `display_chart` 와 동일 **7종**(scatter/
line/bar/box/histogram/ecdf/heatmap)을 클라이언트에서 직접 렌더한다.

### API 라우터 (`backend/router.py`, prefix `/api/ext/evaluator`)

호스트 Origin 가드를 재사용한다(`dependencies=[Depends(require_local_origin)]`). 경로 해석은
`core.result_store.resolve_result_path` 로 일원화(RESULT_DIR 절대 기준 + containment).

| 엔드포인트 | 동작 |
|---|---|
| `GET /dataset?path=&select=&sort=&legend=&...` | 소스 parquet → 선택 항목 리스트(`items`: distinct 키별 `{key, sort, desc}`) + 차트 포인트(`points`: `{key, x, y, legend}` 전체 행) + `schema`(`[{name,dtype}]`, 매핑 UI 드롭다운용). `legend` 는 **반복 쿼리 파라미터로 다중**(`_legend_expr` 가 `" \| "` 합성), x/y 는 빈 값이면 null(차트 종류별 한쪽만 쓰는 경우 대응). 소형 데이터 전제로 1회 전량 전송 |
| `GET /sources?path=` | 현재 소스가 속한 세션의 parquet 후보 목록(`<session>/_artifacts.jsonl` manifest 우선, 없으면 세션 폴더 디스크 스캔 폴백) — 소스 추가/변경 picker 카탈로그 |
| `GET /preview?path=&rows=10` | parquet head(N) + 스키마(NaN/inf·비원시 타입 JSON-safe) — picker 가 **호스트 ArtifactData 와 동일한 형태**의 미리보기 테이블을 그려 어떤 소스인지 보고 고르게 한다. `scan_parquet` 으로 total_rows 만 집계(전량 로드 없음) |
| `GET /state?path=` | 저장된 큐레이션 상태(선택·순서·**mark·mapping**) 로드. 없거나 손상 시 빈 상태 폴백 |
| `POST /state {path, selected, order, mark, mapping}` | 큐레이션 상태(차트 종류·컬럼 매핑 포함)를 소스 옆 사이드카에 저장 (저장하기) |
| `POST /export {path, selected, mapping, excluded, note}` | 선택 항목만 필터 + 차트 Filter 제외 행 실제 삭제(`excluded`: 선택키별 0-based point 인덱스) + sort 정수 재계산 → 새 parquet (내보내기). 응답에 **큐레이션 요약** `summary{total, selected, dropped, excluded_rows, note}` 동봉(`total`=소스 select distinct 수) — 사람의 결정을 메인 앱 칩으로 환류 |

### ColumnMapping — 컬럼 역할 (`ColumnMapping` 모델)

`mapping` 의 **키는 evaluator 가 해석하는 고정 역할**, 값은 도메인 실제 컬럼명. 미지정 시 예시 기본값.
역할은 **공통**(차트 무관 — select/sort/legend/desc)과 **차트별**(mark 가변 — x/y)로 나뉜다.

| 역할 키 | 군 | 의미 | 기본값 |
|---|---|---|---|
| `select` | 공통 | 좌측 리스트 항목의 고유 키 | `item_id` |
| `sort` | 공통 | 정렬·내보내기 순위(정수, export 시 재계산 대상) | `rank` |
| `legend` | 공통 | 시리즈 그룹(범례) — **다중 컬럼 허용**(`list[str]`, `" \| "` 합성) | `["category"]` |
| `desc` | 공통 | 리스트 보조 설명 (**선택적** — 컬럼 부재 시 desc=None 폴백, `_resolve_desc_expr`) | `item_desc` |
| `x` | 차트별 | 차트 가로축 (scatter/line/bar/histogram/ecdf/heatmap) | `tkout_time` |
| `y` | 차트별 | 차트 세로축 (scatter/line/bar/box/heatmap) | `value` |

> **`legend` 는 `list[str]`** 이다 — UI 의 토글 칩 다중 선택을 합성 그룹(`POR | A`)으로 만든다.
> **`x`/`y` 는 빈 문자열이면 '미매핑'** 으로 취급해 `required_columns()` 에서 제외한다(histogram 은
> x 만, box 는 y 만 쓰므로). `desc` 도 선택적. **select·sort 와 매핑된 x/y/legend 컬럼**만 부재 시
> `/dataset` 422. `ColumnMapping` 은 `extra="ignore"` 라 프론트가 차트 옵션(`mark`·`aggregate`)을
> 같은 매핑 객체에 실어 보내도 export 검증을 깨지 않는다(비-컬럼 키는 조용히 무시).

### 상태 사이드카 · export 규칙

- **상태 사이드카** `<stem>.evaluator-state.json` — 소스 parquet 과 같은 폴더에 형제로 저장
  (`selected` 키 목록 + `order` 전체 순서 + **`mark` 차트 종류 + `mapping` 컬럼 매핑 오버라이드**).
  재진입 시 `selected`/`order` 는 현재 아이템 집합과 정확히 일치할 때만 복원하고, `mark`/`mapping`
  은 있으면 번들/쿼리 기본값보다 우선한다(사용자가 도구 안에서 바꾼 차트 설정 영속). `mapping` 은
  데이터 투영을 바꾸므로 `loadActiveSource` 가 **상태를 먼저 읽고** 그 매핑으로 `/dataset` 을 요청한다.
- **export 정수 재계산**: `selected` 가 곧 최종 리스트 순서이며, 그 순서대로 sort 컬럼을 1..N 정수로
  덮어쓴다(같은 선택키의 모든 행이 동일 정수). 결과는 `<stem>.curated.parquet` 으로 쓴다.
- **차트 Filter 제외 반영(데이터에 실제 삭제)**: `excluded`(선택키별 0-based point 인덱스)의 행을
  최종 parquet 에서 **실제로 제거**한다 — 차트 Filter 는 '이 행을 분석 데이터에서 뺀다'는 결정이므로
  메타데이터가 아니라 데이터에 반영한다(레전드 순서·색상·Hide 는 시각 전용이라 미반영). 프론트
  `pointsByKey` 인덱스와 정합하도록 백엔드가 `pl.int_range(0, pl.len()).over(key)` 로 키별 행 순번
  `__pos__` 를 만들어 `(key, pos)` anti-join 으로 빼낸다(`_apply_point_exclusions`). 남는 행이 0이면 422.
- **세션 manifest 기록**: export 시 산출물을 **세션 루트** `_artifacts.jsonl` 에 best-effort append
  (`curated.parent.parent` = 세션 루트 전제). 채팅 에이전트의 산출물 재발견(`read_manifest_entries`)이
  큐레이션 결과도 보게 한다. 호스트 private 상수에 의존하지 않으려고 `_MANIFEST_FILENAME` 을
  **의도적으로 복제**(호스트 리팩토링에 격리).
- **메인 앱 실시간 인폼(export-back) + 루프 환류**: 내보내기 성공 시 프론트가
  `BroadcastChannel("evaluator:exports")` 로 `{type:"export", session, path, filename, rows, columns,
  summary}` 를 post 한다(`session` 은 소스 경로의 `<session>`, `summary` 는 `/export` 응답). 같은 출처인
  메인 앱 탭의 `frontend/src/lib/evaluatorBridge.svelte.js` 가 구독해, 그 세션의 **마지막 어시스턴트
  메시지에 parquet 데이터 칩**을 붙이고(`payload.summary` 보존, 활성 세션이면 패널 오픈) localStorage
  영속시킨다(재내보내기 시 `_refreshSummary` 로 같은 경로 칩의 요약 갱신). 칩이 메시지에 임베드되므로
  새로고침 후에도 남는다. 별도 탭이므로 채팅 SSE 가 아닌 BroadcastChannel 을 쓴다.
  - **칩 요약 + 1클릭 후속**: `ArtifactData.svelte` 가 `payload.summary` 를 요약 배너(후보 N개 중
    M개 선택·X행 제외·메모)로 띄우고, **"이어서 작업"** 버튼이 `artifactActions.seedCurationFollowup`
    으로 결정 맥락 머리말 + 큐레이션 경로 pill 을 컴포저에 시드한다(기존 `ui.composerSetParts` 신호
    재사용 — 사람이 검토 후 전송하면 에이전트가 큐레이션 결정을 안고 이어서 작업). 사람의 판단이
    에이전트에게 보이도록 루프를 닫는다.

### 프론트 진입 (`frontend/src/App.svelte`)

URL 쿼리로 데이터 소스를 받는다. `onMount` 에서 읽어 데이터셋·상태를 로드한다.

| 진입 | 의미 |
|---|---|
| `?path=result/<session>/<ts>/x.parquet` | 단일 소스 직접 지정 (`&legend=a&legend=b` 다중 가능) |
| `?bundle=result/.../<tool>.bundle.json` | 다중 소스 contract(`open_curation` 산출). 번들을 fetch 해 `sources`·`mapping`(legend str|list 둘 다)·선택적 `mark` 확정 — `path` 보다 우선 |
| (둘 다 없음) | **랜딩 페이지**(`landing`) — 안내 메시지 + `result/…parquet` 경로 입력. 패널 런처로 소스 없이 열릴 때. 입력 후 단일 소스로 적재(이후 ⚙ 매핑·소스 변경으로 보강) |

- **다중 소스 = 소스 탭**: 성격 다른 후보군 전제라 **병합하지 않고** 소스마다 탭으로 한 번에 하나씩
  큐레이션한다(각 탭은 단일 소스 엔드포인트 재사용, 탭 전환 시 선택·순서·**매핑·mark·schema** 를
  stash 에 보존·복원). 단일 소스면 탭바를 숨긴다.
- **차트 종류 셀렉터 + 매핑 설정 모달**: 본문 상단 세그먼트로 차트 종류(7종)를 바꾸고(데이터 재요청
  없이 재렌더만), **⚙ 매핑 설정** 모달에서 역할별 **설명 + 컬럼 드롭다운**으로 매핑한다. 모달은
  공통 역할(select/sort/legend/desc)을 항상, 차트별 역할(x/y/aggregate)을 선택한 mark 에 맞춰
  노출한다. legend 는 컬럼 토글 칩 **다중 선택**(순서=합성 순서). 컬럼 역할이 바뀌면 `/dataset` 을
  재요청하되 **선택키 집합이 그대로면 사용자의 선택·순서를 보존**한다(`applyMappingConfig`).
- **소스 교정 picker**: `GET /sources` 카탈로그 + `GET /preview` head(10) 미리보기(좌측 후보 리스트 +
  우측 미리보기 테이블의 마스터-디테일)로 어떤 소스인지 보고 **추가**(새 탭)·**제거**(탭 ×)·**변경**
  (단일 소스 전용 1단축 교체)한다. 단일 소스 진입은 헤더가 '+ 소스 추가' 대신 '소스 변경' 을 띄운다.
- **좌측 패널 너비 조절**: 사이드바 우측 경계의 `.col-resizer` 를 pointer 드래그(`sidebarWidth` clamp
  220–640). **진입 시 전부 체크(선택)** 가 기본 — 저장된 상태가 전혀 없을 때만 적용하고, 사이드카가
  있으면 그대로 복원한다(`applyDataset` 의 `noSaved` 분기).
- **리스트 검색·필터·일괄 선택**: 검색(key·desc 부분일치)·legend 필터(`legendByKey` 합집합 드롭다운)로
  `filteredOrder`(가시 순서)를 좁히고, 전체/해제/반전 일괄 버튼이 **가시 집합에만** 적용된다. 필터는
  **표시만** 좁히고 순서·내보내기 의미는 불변 — `order`/`selected` 는 전체 기준 유지, cursor 는
  `filteredOrder` 기준(필터 변동 시 클램프).
- **순서 변경 = 드래그&드롭**: 리스트 행을 `draggable` 로 끌어 다른 행 위에 놓으면 순서를 재배치한다
  (`onItemDrop` — 드래그 키를 전체 `order` 에서 빼서 드롭 대상 키의 전체 order 위치 앞에 삽입).
  필터가 걸려 중간에 숨은 항목이 있어도 항상 전체 order 기준으로 정합한다. 드롭 대상 행은 상단 라인
  인디케이터(`.row.drag-over`)로 표시. (이전의 ↑↓ 버튼·`orderIndex` 인접 교환을 대체.)
- **병합 보기(merge)**: 본문 상단 **차트 보기 제어**의 토글. 표시 선택(`displaySelection`)된 차트들의
  points 를 `mergePoints(pointsByKey, order∩displaySelection)` 로 단순 결합해 단일 standalone
  `ChartCell`(읽기전용 — brush 미연결)로 렌더한다. 조망과 달리 **legend 를 항목 키로 덮어쓰지 않고
  원래 legend 매핑을 보존**한다(항목별 차트의 매핑 요소 유지, 소스 데이터만 합침). per-key chartState
  스냅샷은 건드리지 않는다. **전체 보기/보기 해제** 버튼이 `displaySelection` 을 가시 집합 전체/빈
  값으로 일괄 설정한다.

### 차트 그리드·라이트박스 (클라이언트 사이드)

본문은 메인 앱 `display_chart` 의 UX 를 **클라이언트에서 자체 구현**한다 — points 가 `/dataset` 으로
이미 적재돼 있고, 차트 상호작용은 클라이언트 상태라 격리 원칙상 메인 앱의 spec→render→`/api/chart/filter`
파이프라인에 결합하지 않는다. **Filter 제외는 내보내기 시 데이터에 반영**(export `excluded` 로 전송 →
백엔드가 실제 행 삭제)되고, 레전드 순서·색상·Hide 는 **시각 전용**(선택/순서/export 에 무영향)이다.

| 파일 | 역할 |
|---|---|
| `lib/chartOption.js` | **mark 별 빌더 디스패처** `buildChartOption(mark, points, snapshot, opts)` → 7종(scatter/line/bar/box/histogram/ecdf/heatmap) ECharts option. 제외·레전드(순서·색상·Hide) 반영 + brush 환원용 `row_ids` + `brushable` 플래그 + 매핑 누락 시 친절한 `error`. **brushable 차트(scatter/line/ecdf)는 option 에 `brush` 컴포넌트(`BRUSH_COMPONENT`)를 포함**해야 라이트박스의 `takeGlobalCursor(key:"brush")` 가 박스 선택을 활성화한다(메인 앱 `render_spec_to_echarts` 의 `"brush": {}` 와 동일 역할 — 누락 시 드래그 box select 무동작). line/ecdf 는 투명 scatter overlay 로 brush 우회(메인 앱 `_with_brush_overlay` 패턴), bar/box/histogram/heatmap 은 비-brush(legend Filter 만). box/histogram/ecdf 통계는 JS 로 계산(메인 앱 알고리즘과 동치 — 분위수 선형보간·10빈·누적비율). `mergePoints(pointsByKey, keys)` 는 병합 보기용 결합(legend 보존). `MARKS`/`MARK_BY_ID`/`AGGREGATES` 메타데이터를 매핑 UI 와 공유 |
| `lib/chartState.svelte.js` | 선택키별 `{stack:[snapshot], cursor}` undo/redo 스토어. snapshot = `{excluded:number[], legend:{order,colors,hidden}}`. 그리드·라이트박스가 같은 스토어를 봐 동시 재렌더(메인 앱 chartCache 단일소스 패턴) |
| `lib/ChartCell.svelte` | 단일 ECharts(embedded 그리드 셀 / standalone 라이트박스). `mark`·`roles`·`aggregate` props 로 빌더 분기. 매핑 누락 시 안내 문구. **embedded 셀은 `brush` 컴포넌트를 제거(`renderOption`)** 해 클릭=확대 전용으로 두고, standalone 은 brush 를 유지하고 `onchart(chart, row_ids)` 로 라이트박스에 통지(라이트박스가 takeGlobalCursor 로 활성화) |
| `lib/ChartGrid.svelte` | 제목 패널 + 페이지당 6개 페이지네이션. `mark`/`roles`/`aggregate` 를 셀에 전달. 셀 클릭 → 라이트박스 |
| `lib/ChartLightbox.svelte` | 리사이즈 확대 모달 + Filter/Filter All/Reset/Undo/Redo + 레전드 편집 패널. brush 는 `brushable` 차트에서만 활성(집계 차트는 legend Filter 만). **인라인 SVG 아이콘**(evaluator 는 오프라인-퍼스트라 메인 앱의 Material Symbols CDN 미사용) |

- **표시 선택 = 클릭 / Ctrl·⌘+클릭 / Shift+클릭**: 좌측 항목을 클릭하면 단일 표시, Ctrl/⌘+클릭으로
  표시 집합 토글, **Shift+클릭으로 앵커~클릭 사이 가시 범위 선택**(파일 탐색기 류 UX — `displayAnchor`
  기준, Ctrl/⌘+Shift 는 기존 선택에 범위 누적). `displaySelection` 은 체크박스의 큐레이션 선택과 별개.
  **전체 보기/보기 해제** 버튼이 `displaySelection` 을 가시 집합 전체/빈 값으로 설정한다. `chartState`
  식별자는 `${activePath}::${key}` 로 네임스페이스해 소스 간 같은 키가 필터 상태를 공유하지 않게 한다.
- **Filter 의미**: brush 점 또는 레전드 그룹 선택 → 해당 점/그룹을 제외. *Filter All* 은 표시 중인 모든
  차트에 제외(brush 는 선택 점이 속한 레전드 값을 모든 차트에서 제외). Reset/Undo/Redo 는 현재 차트 키의
  스택만 조작. **이 제외(`snapshot.excluded`)는 내보내기 시 선택키별로 모여 export `excluded` 로 전송돼
  최종 parquet 에서 실제 행이 삭제된다**(`App.svelte` `collectExclusions`).

---

## SKILL 작성 예시 (`SKILLS/rank_review.md`)

큐레이션 핸드오프를 따르는 SKILL 작성 표준. `requires_tools: [exec_code, save_artifact, open_curation]`,
2단계 plan(`후보 데이터 산출` → `큐레이션 핸드오프`), **마지막에 `open_curation` 을 한 번만** 호출.
`mapping` 의 역할 키는 고정, 값(컬럼명)만 도메인에 맞게 바꿔 복사한다.

→ 새 도메인 적용: 이 SKILL 을 복사해 매핑 표의 값만 교체. 역할 키는 절대 바꾸지 않는다.

## Mock 검증 (`docs/mock-scenarios.md` 시나리오 H)

`exec_code`(후보) → `save_artifact`(parquet) → `open_curation` 핸드오프 흐름을 실 LLM 없이 검증한다
(트리거: `순위 검토`·`후보 큐레이션`·`큐레이션 도구`). 진입 카드 markdown 칩 렌더 + 새 탭
`/ext/evaluator/?bundle=` 링크가 `rank_review` SKILL 의 핸드오프 계약과 동일한지 확인.

---

## 새 확장 추가하기 (절차)

1. `extensions/<tool>/backend/router.py` 에 `get_router() -> APIRouter` 작성
   (prefix `/api/ext/<tool>`, 절대 import 만, Origin 가드 의존성 재사용 권장).
2. `extensions/<tool>/frontend/` 에 Svelte5 SPA 작성 → `npm run build` 로 `dist/` 생성
   (라우터 없이 SPA만, 또는 SPA 없이 라우터만도 가능).
3. (선택) `backend/agent/tools/curation.py` 의 `open_curation(tool="<tool>", ...)` 로 진입 카드를
   띄우는 SKILL 을 `SKILLS/` 에 작성. `tool` 인자만 바꾸면 evaluator 가 아닌 새 확장도 가리킨다.
4. host 코드 수정 불필요 — dev 는 재기동 시, frozen 은 다음 빌드에서 자동 반영.
