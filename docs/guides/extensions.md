# 확장 시스템 (Extensions) 가이드

확장(extension)은 **메인 앱과 격리된 독립 도구**(Svelte5 SPA + FastAPI 라우터)다. 폴더 단위로
추가·삭제할 수 있고 host 코드 수정이 필요 없다. AI Agent 가 만든 산출물을 사람이 더 풍부하게
조작해야 할 때(예: parquet 후보를 시각적으로 검토·선별) 채팅 UI 만으로 부족한 도메인 화면을
확장으로 붙인다.

예시 확장: **evaluator** (`extensions/evaluator/`) — parquet 큐레이션 BI.

> 이 문서는 **확장을 만들고 에이전트에 연결하는 개발자**를 위한 것이다. 로더·번들·격리 원칙의
> 내부 구현은 → `.claude/rules/extensions_architecture.md`.

---

## 핵심 개념: 확장은 우측 아티팩트 패널에서 열린다

확장 SPA 는 **메인 앱과 같은 출처(host:port)** 에서 정적 서빙되며, 채팅창 **우측 아티팩트 패널에
iframe 으로 임베드**되어 열린다. 격리된 빌드 SPA 를 그대로 재사용하므로 same-origin iframe 이
유일하게 합리적인 임베드 방식이다 — iframe 안의 에셋·`/api/ext/<tool>` 호출이 same-origin 으로
동작하고 Origin 가드도 통과한다.

확장을 패널에 여는 경로는 두 가지다:

| 경로 | 진입 | 영속성 |
|---|---|---|
| **에이전트 핸드오프** | `open_curation` 도구 → `kind:"extension"` 칩(번들 포함) | 메시지에 영속 (세션 재진입 시 복원) |
| **사용자 런처** | TopBar 패널-열기 버튼의 **드롭다운** → 소스 없이 확장 열기 | 휘발 (대화 산출물 아님) |

두 경로 모두 패널 헤더의 **'새 탭'** 버튼으로 별도 브라우저 창에서도 열 수 있다
(`ArtifactExtension.svelte`).

---

## 디렉터리 컨벤션

```
extensions/<tool>/
  extension.json       ← (선택) 런처 메타데이터 {name, description, icon}
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
| `<tool>/backend/router.py` `get_router()` | API 라우터 팩토리 | `/api/ext/<tool>` |
| `<tool>/frontend/dist` | 빌드된 SPA(`html=True`) | `/ext/<tool>` |
| `<tool>/extension.json` | (선택) 런처 표시 메타 | `GET /api/extensions` |

라우터·정적 SPA 는 **있는 것만** 마운트된다. 로더(`backend/core/extensions_loader.py`)가
컨벤션으로 자동 발견·마운트하므로 host 코드 수정이 불필요하다.

---

## 에이전트 핸드오프 — `open_curation`

에이전트가 후보 parquet 을 만든 뒤 `open_curation(tool, sources, mapping, mark, title)` 을
**한 번** 호출하면:

1. `tool` 이름·`sources`(parquet containment)·`mapping`(평탄 dict) 검증.
2. 번들 스펙 `<tool>.bundle.json`(`{tool, sources, mapping, mark?}`)을 현재 턴 슬롯에 쓴다.
3. `ToolResult.data = {kind:"extension", tool, src:"/ext/<tool>/?bundle=...", title, bundle}` 반환.
4. 프론트가 우측 패널에 확장 SPA 를 iframe 으로 임베드하고 자동으로 연다.

`tool` 인자로 임의 확장을 가리킬 수 있는 **제네릭 진입 훅**이다 — `mapping` 도 호스트가 해석하지
않고 번들에 그대로 실어 보낸다(확장이 해석). 폴더를 지우면 SKILL 이 호출하지 않아 무해(no-op).

도구 인자·예시는 → [builtin-tools.md](builtin-tools.md) 의 `open_curation`. SKILL 작성 표준은
→ [SKILLS/rank_review.md](../SKILLS/rank_review.md) (역할 키는 고정, 값만 도메인에 맞게 교체).

---

## 사용자 런처 드롭다운 + `extension.json`

TopBar 의 패널-열기 버튼 옆 caret(`ExtensionMenu.svelte`)이 **사용 가능한 확장 목록**을 띄운다.
목록은 부팅 시 `GET /api/extensions` 로 1회 받아 캐시한다(`ui.extensions`).

- `GET /api/extensions` 는 `frontend/dist` 가 있는(=화면이 있는) 확장만 반환한다 — 라우터만 있고
  UI 가 없는 확장은 런처에 띄울 수 없다.
- 각 항목 `{tool, name, description, icon}` 의 표시 이름·설명은 확장 루트의 선택적
  `extension.json` 매니페스트에서 온다. **없으면 폴더명으로 폴백**한다.

```json
// extensions/<tool>/extension.json (선택)
{ "name": "Evaluator", "description": "parquet 후보 데이터 큐레이션", "icon": "evaluator" }
```

런처로 연 확장은 **소스/번들 없이**(`/ext/<tool>/`) 열리므로, 확장은 데이터 없이 열렸을 때
깨지지 않는 **랜딩 페이지**를 갖춰야 한다(아래).

---

## 랜딩 페이지 계약 (데이터 없이 열렸을 때)

확장 SPA 는 `?path=`·`?bundle=` 같은 진입 파라미터가 **없을 때** 빈 화면·에러로 끝나면 안 된다.
대신 **소스 데이터·매핑 입력을 안내하는 랜딩 페이지**를 보여준다. evaluator 의 랜딩(`App.svelte`)은:

- 도구가 무엇인지 + 보통 에이전트의 `open_curation` 핸드오프로 열린다는 **안내 메시지**.
- 직접 검토용 `result/…parquet` **경로 입력 + 불러오기** (로드 후 ⚙ 매핑 설정·소스 변경으로 보강).

---

## 빌드 번들링 (`packaging/App.spec`)

`App.spec` 이 빌드 시 `extensions/*` 를 글롭해 **런타임에 필요한 부분만 선별 번들**한다.

| 포함 | 제외 |
|---|---|
| `<tool>/backend`, `<tool>/frontend/dist`, `<tool>/extension.json` | `node_modules`·`frontend/src`·`tests` |

- 폴더·파일이 **있을 때만** 수집 — 없으면 no-op. 확장 1개 폴더를 지워도 spec 수정 없이 다음
  빌드에 자동 반영.
- **`frontend/dist` 는 `release.ps1` 이 App.spec 보다 먼저 빌드한다**(`extensions/*/frontend` 자동
  발견 → `npm ci/install` + `npm run build`). 빌드를 건너뛰면 stale/누락 dist 가 박힌다.
  → 빌드 순서 상세: `.claude/rules/update_architecture.md`.

---

## 새 확장 추가 절차

1. `extensions/<tool>/backend/router.py` 에 `get_router() -> APIRouter` 작성
   (prefix `/api/ext/<tool>`, **절대 import 만** — 패키지-상대 import 금지, Origin 가드 의존성 재사용 권장).
2. `extensions/<tool>/frontend/` 에 Svelte5 SPA 작성 → `npm run build` 로 `dist/` 생성.
   vite `base` 를 `/ext/<tool>/` 로 설정해 iframe 임베드 시 에셋 경로가 맞게 한다.
   진입 파라미터가 없을 때의 **랜딩 페이지**를 반드시 구현한다.
3. (선택) `extensions/<tool>/extension.json` 으로 런처 표시 이름·설명·아이콘을 지정.
4. (선택) `open_curation(tool="<tool>", ...)` 로 진입시키는 SKILL 을 `SKILLS/` 에 작성.
5. host 코드 수정 불필요 — dev 는 재기동 시, frozen 은 다음 빌드에서 자동 반영.

> dev 에서 iframe 테스트: 메인 프론트의 Vite 가 `/ext` 를 백엔드로 프록시하므로
> (`frontend/vite.config.js`), 백엔드에 확장 `dist` 가 마운트돼 있으면(=`npm run build` 선행) 패널
> iframe 이 로드된다.

---

## 더 보기

- `.claude/rules/extensions_architecture.md` — 로더·격리 원칙·evaluator 상세(엔드포인트·상태 사이드카·
  export 환류).
- [builtin-tools.md](builtin-tools.md) — `open_curation`·`save_artifact` 도구 레퍼런스.
- [mock-scenarios.md](mock-scenarios.md) — 시나리오 H(큐레이션 핸드오프) 검증.
