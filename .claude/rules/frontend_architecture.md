# Frontend 아키텍처

Svelte 5 (runes 모드). 컴포넌트는 상태를 직접 읽고, 변형은 반드시 액션 함수를 통한다.

## 파일 책임 분리

```
lib/
  state.svelte.js       전역 $state 객체 ui + activeSession() 헬퍼
  chatActions.svelte.js 세션·메시지 액션 + presence + 업데이트 + 초기화
  settingsActions.svelte.js LLM 설정 모달 액션 (열기/닫기/저장/테스트)
  api.js                fetch 래퍼 — 컴포넌트는 URL을 직접 모름
  settingsApi.js        설정 관련 fetch 래퍼
  sse.js                parseSseStream(body, onEvent) — SSE 파싱
  storage.js            localStorage CRUD (세션, activeId, 테마)
  markdown.js           renderMarkdown(text) — marked + DOMPurify + hljs
  format.js             autoTitle, relativeTimeBucket

components/
  Sidebar.svelte        세션 목록 + 새 대화 버튼 + 테마 토글 + 설정 아이콘
  SessionItem.svelte    세션 행 (클릭=선택, 더블클릭=인라인 rename, hover=삭제)
  ChatArea.svelte       메시지 스크롤 영역, 하단 자동 스크롤
  MessageBubble.svelte  user(plain text) / assistant(markdown) 버블
  Composer.svelte       auto-resize textarea, Enter=전송 / Shift+Enter=줄바꿈
  TopBar.svelte         현재 세션 제목, 모바일 사이드바 토글
  SettingsModal.svelte  LLM 설정 모달 (프로바이더·모델·API키·Base URL)
  UpdateBanner.svelte   업데이트 알림 배너
  UpdateModal.svelte    업데이트 진행 모달
```

## 상태($state) 패턴

`lib/state.svelte.js`의 `ui` 객체 하나가 전역 진실의 원천.

```js
// 읽기 — 컴포넌트 어디서나
import { ui } from "$lib/state.svelte.js";
ui.sessions;          // Session[]
ui.activeSessionId;
ui.streaming;         // 전송 중 여부 (입력 비활성 가드)
ui.theme;

// 변형 — 반드시 액션 함수 경유
import { sendMessage, createSession } from "$lib/chatActions.svelte.js";
import { openSettings, saveSettings } from "$lib/settingsActions.svelte.js";
```

컴포넌트가 `ui.*`를 직접 write하는 것은 `SettingsModal` 내 draft 편집 필드만 허용한다 (`ui.settingsDraft.*`). 그 외는 전부 액션 함수가 담당.

## localStorage 스키마

```
chat:sessions:v1       Session[]  (아래 타입)
chat:activeSessionId:v1  string | null
chat:theme:v1          "light" | "dark"
```

```ts
type Session = {
  id: string;          // UUID — 백엔드 client_id와 동일
  title: string;
  titleEdited: boolean;
  createdAt: number;   // ms epoch
  updatedAt: number;   // 사이드바 정렬·그룹핑 기준
  messages: Array<{
    id: string;
    role: "user" | "assistant";
    content: string;
    toolStatus: string | null;
    createdAt: number;
  }>;
};
```

**세션 id = 백엔드 client_id**. presence EventSource 채널도 이 id로 열린다.

## 데이터 흐름 방향

로컬스토리지가 진실의 원천이다. 앱 시작 시 흐름은 **프론트 → 백엔드** (hydrate):

```
앱 마운트
  └─ initApp()
       ├─ localStorage 로드 → ui.sessions, ui.activeSessionId
       ├─ openPresence(activeId)     // SSE 연결
       └─ restoreConversation(id, messages)  // POST /api/conversation/restore
                                              // 백엔드 in-memory store를 채움

세션 전환 (selectSession)
  └─ openPresence(newId)  + restoreConversation(newId, ...)

메시지 전송 (sendMessage)
  └─ POST /api/chat → SSE delta 스트림 → localStorage 저장 (debounce 200ms)
```

`GET /api/conversation`은 초기 로드에 사용하지 않는다. LLM context를 채우는 방향이 뒤집혀 있음에 주의.

## 세션 동기화 규칙

| 동작 | presence | 백엔드 restore | localStorage |
|---|---|---|---|
| `createSession()` | 새 id로 open | 호출 안 함 (빈 세션) | prepend + save |
| `selectSession(id)` | 재오픈 | 호출 | save activeId |
| `deleteSession(id)` | (다음 세션으로) | DELETE /api/conversation | 제거 + save |
| `renameSession(id, title)` | — | — | titleEdited=true + save |

`ui.streaming === true`이면 세션 전환·삭제·새 대화 모두 차단.

## 마크다운 렌더링

`lib/markdown.js`의 `renderMarkdown(text)` → `{@html renderMarkdown(msg.content)}`

- assistant 메시지만 마크다운. user 메시지는 `white-space: pre-wrap` plain text.
- `marked` + `DOMPurify` (XSS 방어) + `highlight.js` (코드 펜스)
- 테마 전환 시 `:root` / `[data-theme="dark"]` CSS 변수로 hljs 스타일 분기

## 테마 시스템

`app.css`의 `:root` / `[data-theme="dark"]` CSS 변수 토큰 기반.
`setTheme(theme)`이 `document.documentElement.setAttribute("data-theme", theme)` 호출.
컴포넌트 scoped CSS에서는 `[data-theme="dark"]` 셀렉터를 쓸 수 없음 — 색상값은 반드시 CSS 변수(`var(--color-success)` 등)로 정의하고 `app.css`에서 테마별 분기.
