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

에이전트가 후보 parquet 을 만든 뒤 `open_curation(tool, sources, mapping, title)` 를 **한 번** 호출하면:

1. `tool` 이름 검증(`^[a-z0-9][a-z0-9_-]*$` — `/ext/<tool>/` 경로 세그먼트로 안전) ·
   `sources` 검증(`resolve_result_path` containment + parquet 확장자) · `mapping` 검증(평탄한 str→str).
2. 번들 스펙 `<tool>.bundle.json`(`{tool, sources, mapping}`)을 **현재 턴 슬롯**에 쓴다.
3. 마크다운 카드 `<tool>.curation.md`("🔍 큐레이션 도구 열기" 링크 + 소스 목록)를 같은 슬롯에 쓴다.
4. **기존 markdown 칩 렌더 경로를 그대로 재사용**해 우측 패널에 카드를 표시한다 —
   전용 프론트 컴포넌트 없이 `ToolResult(data={"kind": "markdown", "src", "title"})`.

링크는 `/ext/<tool>/?bundle=<URL인코딩 result 경로>` 를 가리킨다. 사용자가 카드의 링크를 클릭하면
새 탭에서 확장 SPA 가 열려 번들의 parquet 들을 로드한다.

| 항목 | 처리 |
|---|---|
| markdown 칩 인식 | 프론트 `chatActions.svelte.js` 의 `_ARTIFACT_TOOL_NAMES` 에 `open_curation` 1줄 등록 → display_* 와 동일 칩 렌더 |
| 새 탭 강제 | `frontend/src/lib/markdown.js` 의 DOMPurify `afterSanitizeAttributes` 훅이 **모든 `<a>`** 에 `target="_blank"`+`rel="noopener noreferrer"` 부여 (DOMPurify 기본 `ALLOWED_ATTR` 에 `target` 부재라 훅 필수 — 그냥 두면 제거됨) |
| evaluator 비특정(제네릭) | `tool` 인자로 임의 확장을 가리키고 `mapping` 도 해석 없이 번들에 그대로 실어 보낸다(확장이 해석). 확장 진입 규약을 한 곳에 모은 호스트 훅 |
| 폴더 삭제 시 | SKILL 이 `open_curation` 을 호출하지 않으므로 무해(no-op) |

> 카드는 **평범한 마크다운 링크만** 쓴다(raw HTML 금지) — 새 탭 부여는 위 DOMPurify 훅이 담당한다.
> 새 탭으로 여는 이유: 데스크탑 앱은 채팅이 곧 전체 창이라 같은 탭 이동 시 세션이 소실된다.

---

## 예시 확장: evaluator (`extensions/evaluator/`)

AI Agent 가 만든 parquet 산출물을 **사람이 시각적으로 검토·선별·재정렬**해 최종 리포트용 데이터로
만드는 큐레이션 UI. 좌측 선택 리스트(체크·순서 변경) + 본문 scatter 차트 + 하단 저장/내보내기.

### API 라우터 (`backend/router.py`, prefix `/api/ext/evaluator`)

호스트 Origin 가드를 재사용한다(`dependencies=[Depends(require_local_origin)]`). 경로 해석은
`core.result_store.resolve_result_path` 로 일원화(RESULT_DIR 절대 기준 + containment).

| 엔드포인트 | 동작 |
|---|---|
| `GET /dataset?path=&select=&sort=&...` | 소스 parquet → 선택 항목 리스트(`items`: distinct 키별 `{key, sort, desc}`) + scatter 포인트(`points`: `{key, x, y, legend}` 전체 행). 소형 데이터 전제로 1회 전량 전송 |
| `GET /sources?path=` | 현재 소스가 속한 세션의 parquet 후보 목록(`<session>/_artifacts.jsonl` manifest 우선, 없으면 세션 폴더 디스크 스캔 폴백) — 소스 추가/변경 picker 카탈로그 |
| `GET /preview?path=&rows=10` | parquet head(N) + 스키마(NaN/inf·비원시 타입 JSON-safe) — picker 가 **호스트 ArtifactData 와 동일한 형태**의 미리보기 테이블을 그려 어떤 소스인지 보고 고르게 한다. `scan_parquet` 으로 total_rows 만 집계(전량 로드 없음) |
| `GET /state?path=` | 저장된 큐레이션 상태(선택·순서) 로드. 없거나 손상 시 빈 상태 폴백 |
| `POST /state {path, selected, order}` | 큐레이션 상태를 소스 옆 사이드카에 저장 (저장하기) |
| `POST /export {path, selected, mapping}` | 선택 항목만 필터 + sort 정수 재계산 → 새 parquet (내보내기) |

### ColumnMapping — 컬럼 역할 (`ColumnMapping` 모델)

`mapping` 의 **키는 evaluator 가 해석하는 고정 역할**, 값은 도메인 실제 컬럼명. 미지정 시 예시 기본값.

| 역할 키 | 의미 | 기본값 |
|---|---|---|
| `select` | 좌측 리스트 항목의 고유 키 | `item_id` |
| `sort` | 정렬·내보내기 순위(정수, export 시 재계산 대상) | `rank` |
| `x` | 본문 scatter x축 | `tkout_time` |
| `y` | 본문 scatter y축 | `value` |
| `legend` | scatter 시리즈 그룹(범례) | `category` |
| `desc` | 리스트 보조 설명 | `item_desc` |

### 상태 사이드카 · export 규칙

- **상태 사이드카** `<stem>.evaluator-state.json` — 소스 parquet 과 같은 폴더에 형제로 저장
  (`selected` 키 목록 + `order` 전체 순서). 재진입 시 현재 아이템 집합과 정확히 일치할 때만 복원.
- **export 정수 재계산**: `selected` 가 곧 최종 리스트 순서이며, 그 순서대로 sort 컬럼을 1..N 정수로
  덮어쓴다(같은 선택키의 모든 행이 동일 정수). 결과는 `<stem>.curated.parquet` 으로 쓴다.
- **세션 manifest 기록**: export 시 산출물을 **세션 루트** `_artifacts.jsonl` 에 best-effort append
  (`curated.parent.parent` = 세션 루트 전제). 채팅 에이전트의 산출물 재발견(`read_manifest_entries`)이
  큐레이션 결과도 보게 한다. 호스트 private 상수에 의존하지 않으려고 `_MANIFEST_FILENAME` 을
  **의도적으로 복제**(호스트 리팩토링에 격리).

### 프론트 진입 (`frontend/src/App.svelte`)

URL 쿼리로 데이터 소스를 받는다. `onMount` 에서 읽어 데이터셋·상태를 로드한다.

| 진입 | 의미 |
|---|---|
| `?path=result/<session>/<ts>/x.parquet` | 단일 소스 직접 지정 |
| `?bundle=result/.../<tool>.bundle.json` | 다중 소스 contract(`open_curation` 산출). 번들을 fetch 해 `sources`·`mapping` 확정 — `path` 보다 우선 |

- **다중 소스 = 소스 탭**: 성격 다른 후보군 전제라 **병합하지 않고** 소스마다 탭으로 한 번에 하나씩
  큐레이션한다(각 탭은 단일 소스 엔드포인트 재사용, 탭 전환 시 선택·순서를 stash 에 보존·복원). 단일
  소스면 탭바를 숨긴다.
- **소스 교정 picker**: `GET /sources` 카탈로그 + `GET /preview` head(10) 미리보기(좌측 후보 리스트 +
  우측 미리보기 테이블의 마스터-디테일)로 어떤 소스인지 보고 **추가**(새 탭)·**제거**(탭 ×)·**변경**
  (단일 소스 전용 1단축 교체)한다. 단일 소스 진입은 헤더가 '+ 소스 추가' 대신 '소스 변경' 을 띄운다.

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
