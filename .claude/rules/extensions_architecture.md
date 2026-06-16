# 확장 시스템 (Extensions) 아키텍처

`extensions/` 는 **메인 앱과 완전히 격리된 독립 도구**(Svelte 5 SPA + FastAPI 라우터)를 담는다.
호스트는 개별 도구를 모르고 **컨벤션**(`<tool>/backend/router.py` 의 `get_router()` +
`<tool>/frontend/dist`)만 따른다. 따라서 폴더 단위로 추가·삭제할 수 있고 host 코드 변경이 필요 없다.

evaluator 심화 문서(API 라우터·ColumnMapping·export·차트 구현) -> [extensions_evaluator.md](extensions_evaluator.md).

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
    router.py          <- get_router() -> APIRouter (prefix="/api/ext/<tool>")
    tests/             <- 확장 자체 테스트 (번들 제외)
  frontend/
    src/ ...           <- Svelte5 SPA 소스 (번들 제외)
    dist/              <- npm run build 산출물 (정적 서빙 대상 - 번들 포함)
  extension.json       <- (선택) {name, description, icon} - 런처 드롭다운 표시 이름
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

- **경로 단일 진실원천**: `_extensions_dir()` = `_project_root() / "extensions"` - frozen 은
  `MEIPASS/extensions`, dev 는 `PROJECT_ROOT/extensions` (`core.config._project_root` 분기 재사용).
- **파일 경로 적재로 frozen 대응**: 라우터 모듈을 name-import 가 아니라
  `importlib.util.spec_from_file_location(f"ext_{name}_router", router_py)` 로 **flat(점 없는)
  모듈명**으로 적재한다. PyInstaller onefile 이 datas 를 `MEIPASS` 디스크로 추출하므로 `router.py`
  를 파일에서 읽어 실행할 수 있고, flat 모듈명이라 패키지-상대 import 부재 문제를 피한다.
- **확장별 격리**: `_mount_extension` 호출을 `try/except Exception` 으로 감싸 한 확장의 로드 실패가
  앱 전체 부팅을 막지 않게 한다(`logger.warning` 후 다음 확장 진행).
- **`get_router()` 검증**: 팩토리 미정의·`APIRouter` 아닌 반환은 경고 후 건너뛴다(부팅 계속).
- **`extensions/` 부재 시 즉시 return** -> no-op.

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
| `<tool>/backend` -> `MEIPASS/extensions/<tool>/backend` | `node_modules` · `frontend/src` · `tests` (EXE 비대화 방지) |
| `<tool>/frontend/dist` -> `MEIPASS/extensions/<tool>/frontend/dist` | |

- 폴더(`backend`·`dist`)가 **있을 때만** `datas` 에 추가 - 없거나 비면 빈 리스트 -> **no-op**.
- 확장 1개 폴더를 지워도 spec 수정 없이 다음 빌드에 자동 반영(삭제 = 미수집).
- 로더가 런타임에 파일 경로로 적재하므로 `collect_submodules`/`hiddenimports` 가 **불필요**하다.

> **`frontend/dist` 는 `release.ps1` 이 App.spec 보다 먼저 빌드한다.** App.spec 은 dist 가 "있을
> 때만" 번들하므로, 빌드를 안 하면 stale/누락 dist 가 박힌다. `release.ps1` 이 `extensions/*/frontend`
> 를 폴더 컨벤션으로 자동 발견해 `npm ci/install`(node_modules 부재 시) + `npm run build` 한다 -
> 한 확장의 빌드 실패는 경고 후 계속(격리). 상세 -> `update_architecture.md`.

---

## 진입 규약 - `open_curation` (`backend/agent/tools/curation.py`)

에이전트가 후보 parquet 을 만든 뒤 `open_curation(tool, sources, mapping, mark, title)` 를 **한 번** 호출하면:

1. `tool` 이름 검증(`^[a-z0-9][a-z0-9_-]*$`) · `sources` 검증(`resolve_result_path` containment + parquet 확장자) · `mapping` 검증(평탄한 `{str: str | list[str]}` - legend 등 다중 컬럼 역할을 위해 리스트 값 허용).
2. 번들 스펙 `<tool>.bundle.json`(`{tool, sources, mapping}` + 선택적 `mark`)을 **현재 턴 슬롯**에 쓴다.
   `mark`(기본 차트 종류)는 호스트가 해석하지 않는 **제네릭 통과값** - 비어있으면 키 자체를 생략.
3. `ToolResult(data={"kind": "extension", "tool", "src", "title", "bundle"})` 를 반환 -
   `src` 는 `/ext/<tool>/?bundle=<URL인코딩 result 경로>`. 프론트는 이 칩을 **우측 아티팩트
   패널에 확장 SPA 를 same-origin iframe 으로 임베드**하는 `ArtifactExtension.svelte` 로 렌더하고
   자동으로 연다.

| 항목 | 처리 |
|---|---|
| extension 칩 인식 | 프론트 `chatActions.svelte.js` 의 `_ARTIFACT_TOOL_NAMES` 에 `open_curation`, `_ARTIFACT_KINDS` 에 `extension` 등록 -> 칩 자동 생성·패널 자동 오픈 |
| 패널 iframe 임베드 | `ArtifactPanel` 의 kind 분기가 `ArtifactExtension` 로 `<iframe src=payload.src>` 렌더. evaluator `vite base="/ext/evaluator/"` 라 iframe 내 에셋·`/api/ext` 호출이 same-origin -> Origin 가드 통과 |
| '새 탭' 버튼 | `ArtifactExtension` 헤더의 버튼이 `window.open(payload.src, "_blank", "noopener,noreferrer")` 로 별도 창 |
| 영속 | 칩이 메시지(`artifactChips`)에 임베드되어 localStorage 로 영속 - 세션 재진입 후에도 같은 번들로 iframe 복원 |
| 폴더 삭제 시 | SKILL 이 `open_curation` 을 호출하지 않으므로 무해(no-op) |

> iframe 임베드로 여는 이유: 데스크탑 앱은 채팅이 곧 전체 창이라 같은 탭 이동 시 세션이 소실되고,
> 새 탭은 맥락을 끊는다. same-origin iframe 은 격리된 빌드 SPA 를 그대로 재사용하면서 패널 안에서
> 보게 한다. 별도 창이 필요하면 헤더 '새 탭' 버튼을 쓴다.

---

## 패널 런처 드롭다운 + `extension.json`

TopBar 패널-열기 버튼 옆 caret(`ExtensionMenu.svelte`)이 **사용 가능한 확장**을 띄운다. 부팅 시
`GET /api/extensions`(=`list_available_extensions()`)를 1회 받아 `ui.extensions` 에 캐시한다.

- `frontend/dist` 가 있는(=화면이 있는) 확장만 반환 - 라우터만 있는 확장은 런처에 없다.
- 각 항목 `{tool, name, description, icon}` 의 표시 이름·설명은 확장 루트의 선택적
  `extension.json`(`{name, description, icon}`)에서 오고, 없으면 폴더명으로 폴백한다.
- 런처로 연 확장은 `openExtensionPanel(tool)` 이 **휘발 뷰**(`ui.extensionView`, 메시지 칩과 별개)를
  만들어 `/ext/<tool>/`(쿼리 없음=랜딩)로 임베드한다. open_curation 칩은 영속, 런처 뷰는 휘발.
- `extension.json` 은 App.spec 이 확장 글롭에서 번들해 frozen 에서도 enumeration 이 동작한다.

> 확장 SPA 는 `?path=`·`?bundle=` 가 **없을 때** 깨지지 않는 **랜딩 페이지**를 갖춰야 한다 -
> 런처로 소스 없이 열릴 수 있기 때문.

---

## 새 확장 추가하기 (절차)

1. `extensions/<tool>/backend/router.py` 에 `get_router() -> APIRouter` 작성
   (prefix `/api/ext/<tool>`, 절대 import 만, Origin 가드 의존성 재사용 권장).
2. `extensions/<tool>/frontend/` 에 Svelte5 SPA 작성 -> `npm run build` 로 `dist/` 생성
   (라우터 없이 SPA만, 또는 SPA 없이 라우터만도 가능).
3. (선택) `backend/agent/tools/curation.py` 의 `open_curation(tool="<tool>", ...)` 로 진입 카드를
   띄우는 SKILL 을 `SKILLS/` 에 작성. `tool` 인자만 바꾸면 evaluator 가 아닌 새 확장도 가리킨다.
4. host 코드 수정 불필요 - dev 는 재기동 시, frozen 은 다음 빌드에서 자동 반영.
