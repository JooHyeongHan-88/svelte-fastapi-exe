# 프론트엔드 상태 · 데이터 흐름

`frontend_architecture.md` 에서 발췌. `$state` 패턴 · localStorage 스키마 · 데이터 흐름 ·
세션 동기화 · 마크다운 렌더링 · Svelte 5 reactive proxy 주의를 다룬다.

컴포넌트 카탈로그 · 차트 인터랙션 UI · TurnStatus · 테마는
[frontend_components.md](frontend_components.md) 참고.

---

## 상태($state) 패턴

`lib/state.svelte.js`의 `ui` 객체 하나가 전역 진실의 원천.

```js
// 읽기 - 컴포넌트 어디서나
import { ui } from "$lib/state.svelte.js";
ui.sessions;          // Session[]
ui.activeSessionId;
ui.streaming;         // 전송 중 여부 (입력 비활성 가드)
ui.nowTick;           // 생성 중 1초마다 갱신되는 클럭(ms) - TurnStatus 경과 시간 계산용
ui.theme;

// 현재 활성 프로바이더/모델 (ModelPicker 표시용)
ui.currentProvider;                    // "dtgpt" | "openai_compatible" | "mock"
ui.currentModel;                       // 현재 선택된 모델명
ui.modelListByProvider;                // { [provider]: { models, loading, loadedAt } }
ui.modelPickerOpen;                    // 드롭업 열림 여부

// 슬래시 커맨드 - 스킬은 입력창 inline pill(parts {type:"skill"})로 삽입됨 (@인용과 동일 모델).
ui.availableSkills;                    // GET /api/skills 결과 캐시
// 전송 시 sendMessage 가 parts 의 {type:"skill"} 를 force_skills 로 추출 (별도 트레이 상태 없음)

// 아티팩트 패널
ui.activeArtifactId;
ui.artifactPanelOpen;
ui.artifactWidth;                      // 사용자 드래그 조절 패널 너비(px)

// 확장(extensions) 런처
ui.extensions;                         // [{tool, name, description, icon}] - GET /api/extensions 캐시
ui.extensionMenuOpen;                  // TopBar caret 드롭다운 열림 여부
ui.extensionView;                      // 런처로 연 휘발 확장 뷰 {id, kind:"extension", label, payload}

// 아티팩트 라이트박스
ui.lightbox.open;                      // boolean
ui.lightbox.kind;                      // "image" | "chart" | null
ui.lightbox.items;                     // 이미지 전용 payload.items[]
ui.lightbox.index;                     // 현재 보고 있는 항목 인덱스
ui.lightbox.chartKey;                  // 차트 전용 - ui.chartCache 의 키 (payload.src)
ui.lightbox.specPath;                  // 차트 전용 - 필터/레전드 API 에 전달할 spec 경로 (payload.spec)

// 차트 인터랙티브 캐시 (ArtifactChart·ArtifactLightbox 공유)
ui.chartCache;         // Record<src, { items, status, error, canUndo, canRedo }>
// chartCache 갱신 -> 그리드(ArtifactChart)와 라이트박스(ArtifactLightbox) 동시 재렌더.

// 변형 - 반드시 액션 함수 경유
import { sendMessage, createSession } from "$lib/chatActions.svelte.js";
import { openSettings, saveSettings, openModelPicker, selectModel } from "$lib/settingsActions.svelte.js";
import {
  openLightbox, closeLightbox, lightboxNext, lightboxPrev,
  filterChartSelection, undoChartFilter, redoChartFilter, resetChartFilter,
  excludeLegend, setChartLegend,   // 레전드 Filter / 순서·색상·Hide
  artifactRefPath, insertArtifactReference,   // 칩->Composer 경로 참조 삽입
  revealArtifactFolder,   // 패널 헤더 '폴더 열기' - 탐색기 reveal
  loadExtensions, openExtensionPanel,   // 확장 런처 - /api/extensions 캐시·패널에 확장 열기
  toggleExtensionMenu, closeExtensionMenu, closeExtensionView,   // 런처 드롭다운·휘발 뷰 제어
} from "$lib/artifactActions.svelte.js";
```

컴포넌트가 `ui.*`를 직접 write하는 것은 `SettingsModal` 내 draft 편집 필드만 허용한다 (`ui.settingsDraft.*`). 그 외는 전부 액션 함수가 담당.

---

## localStorage 스키마

```
chat:sessions:v1         Session[]
chat:activeSessionId:v1  string | null
chat:theme:v1            "light" | "dark"
```

```ts
type Session = {
  id: string;          // UUID - 백엔드 client_id와 동일
  title: string;
  titleEdited: boolean;
  createdAt: number;   // ms epoch
  updatedAt: number;   // 사이드바 정렬·그룹핑 기준
  messages: Array<{
    id: string;
    role: "user" | "assistant";
    content: string;
    createdAt: number;
    // assistant 메시지 전용
    segments: Segment[] | undefined;   // undefined = 구 형식(legacy)
    activeSkills: string[] | null;
    askUser: { question, slot_key, options, input_type, answered } | null;
    artifactChips: ArtifactChip[];
    isStopped: boolean;
    isFallback: boolean;
    // 진행 상태 타이밍 (assistant 신규 형식)
    streaming: boolean;      // 생성 중 true, 완료/중단 후 false
    startedAt: number;       // 생성 시작 ms
    finishedAt: number | null;
    durationMs: number | null;
  }>;
};
```

**세션 id = 백엔드 client_id**. presence EventSource 채널도 이 id로 열린다.

---

## 데이터 흐름 방향

로컬스토리지가 진실의 원천이다. 앱 시작 시 흐름은 **프론트 -> 백엔드** (hydrate):

```
앱 마운트
  └─ initApp()
       ├─ localStorage 로드 -> ui.sessions, ui.activeSessionId
       ├─ GET /api/app-info -> ui.appName (앱 이름 동적 로드)
       ├─ GET /api/settings -> ui.currentProvider, ui.currentModel
       ├─ openPresence(activeId)     // SSE 연결
       └─ restoreConversation(id, messages)  // POST /api/conversation/restore

세션 전환 (selectSession)
  └─ openPresence(newId)  + restoreConversation(newId, ...)

메시지 전송 (sendMessage)
  └─ POST /api/chat -> SSE delta 스트림 -> localStorage 저장 (debounce 200ms)
```

`GET /api/conversation`은 초기 로드에 사용하지 않는다. LLM context를 채우는 방향이 뒤집혀 있음에 주의.

---

## 세션 동기화 규칙

| 동작 | presence | 백엔드 restore | localStorage |
|---|---|---|---|
| `createSession()` | 새 id로 open | 호출 안 함 (빈 세션) | prepend + save |
| `selectSession(id)` | 재오픈 | 호출 | save activeId |
| `deleteSession(id)` | (다음 세션으로) | DELETE /api/conversation | 제거 + save |
| `renameSession(id, title)` | - | - | titleEdited=true + save |

`ui.streaming === true`이면 세션 전환·삭제·새 대화 모두 차단.

### ESC 재동기화 (중단 턴 desync 치유)

ESC 로 답변을 중지하면 백엔드 `run_turn` 은 그 턴을 store 에 영속하지 않는다(`CancelledError` 는
`BaseException` 이라 영속 경로를 안 탐 — 의도된 설계, → `harness_resilience.md` R1). 반면
localStorage 는 중단 턴을 그대로 보존하므로 **화면(전체 대화)과 백엔드(LLM 컨텍스트, 중단 턴 누락)가
desync** 된다. 그대로 다음 질문을 보내면 LLM 이 직전 맥락을 잃는다.

치유는 프론트가 전담한다 (`chatActions.svelte.js`):
- `stopStreaming()` 이 모듈 플래그 `_needsBackendResync = true` 설정.
- 다음 `sendMessage()` 가 새 턴을 append 하기 **전에**, 플래그가 서 있으면
  `restoreConversation(session.id, toBackendMessages(session.messages))` 로 localStorage 정제본을
  백엔드에 재주입(`{role,content}` 만 — tool_calls 없는 wire-safe)하고 플래그를 내린다(best-effort).
- `selectSession()`·`createSession()` 은 자체 restore/빈 세션이라 시작부에서 플래그를 해제(이월 방지).
  그 외 restore 경로(delete/rewind/initApp)는 self-healing 이라 잔여 플래그가 1회 중복 재동기화를
  유발해도 무해.

---

## 마크다운 렌더링

`lib/markdown.js`의 `renderMarkdown(text)` -> `{@html renderMarkdown(msg.content)}`

- assistant 메시지만 마크다운. user 메시지는 `white-space: pre-wrap` plain text.
- `marked` + `DOMPurify` (XSS 방어) + `highlight.js` (코드 펜스)
- 테마 전환 시 `:root` / `[data-theme="dark"]` CSS 변수로 hljs 스타일 분기

---

## Svelte 5 reactive proxy 주의 (핵심)

`$state` 안의 객체는 Svelte가 reactive proxy로 래핑한다. `sendMessage()` 에서 `assistantMsg`를 plain object로 만들어 `session.messages`에 push한 뒤, `finally` 블록에서 `assistantMsg.streaming = false`로 직접 수정하면 **proxy를 우회**해 반응성이 트리거되지 않는다.

```js
// 잘못된 패턴 - plain object를 직접 수정 (reactive 아님)
const assistantMsg = { streaming: true, ... };
session.messages = [...session.messages, assistantMsg];
// ...나중에...
assistantMsg.streaming = false;  // proxy 우회, 화면 갱신 안 됨

// 올바른 패턴 - reactive proxy를 통해 수정 (stopStreaming과 동일)
const s = activeSession();
const msg = s?.messages.at(-1);
if (msg?.role === "assistant") msg.streaming = false;
```

`stopStreaming()`, `finally` 블록 등 streaming 관련 상태를 후속 설정할 때는 항상 `activeSession().messages.at(-1)` 경로를 사용한다.
