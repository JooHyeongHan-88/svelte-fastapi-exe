# Frontend 아키텍처

Svelte 5 (runes 모드). 컴포넌트는 상태를 직접 읽고, 변형은 반드시 액션 함수를 통한다.

## 파일 책임 분리

```
lib/
  state.svelte.js       전역 $state 객체 ui + activeSession() 헬퍼
  chatActions.svelte.js 세션·메시지 액션 + presence + 업데이트 + 초기화
  settingsActions.svelte.js LLM 설정 모달 + ModelPicker 액션 (열기/닫기/저장/테스트/모델로드)
  api.js                fetch 래퍼 — 컴포넌트는 URL을 직접 모름
  settingsApi.js        설정 관련 fetch 래퍼 (/api/settings/*, /api/app-info)
  sse.js                parseSseStream(body, onEvent) — SSE 파싱
  storage.js            localStorage CRUD (세션, activeId, 테마)
  markdown.js           renderMarkdown(text) — marked + DOMPurify + hljs
  format.js             autoTitle, relativeTimeBucket, formatElapsed, formatDuration

components/
  Sidebar.svelte        세션 목록 + 새 대화 버튼 + 테마 토글 + 설정 아이콘 + ModelPicker
  SessionItem.svelte    세션 행 (클릭=선택, 더블클릭=인라인 rename, hover=삭제)
  ChatArea.svelte       메시지 스크롤 영역, 하단 자동 스크롤
  MessageBubble.svelte  user(plain text) / assistant(markdown) 버블 + 완료 표식
  Composer.svelte       auto-resize textarea, Enter=전송 / Shift+Enter=줄바꿈
  TopBar.svelte         현재 세션 제목, 모바일 사이드바 토글
  ModelPicker.svelte    사이드바 하단 프로바이더/모델 표시 + 빠른 모델 전환 드롭업
  SettingsModal.svelte  LLM 설정 모달 (프로바이더·모델·API키·Base URL)
  UpdateBanner.svelte   업데이트 알림 배너
  UpdateModal.svelte    업데이트 진행 모달
  TurnStatus.svelte     생성 중 진행 표식 — 펄스 점 + 상황별 문구 + 경과 시간
  ArtifactPanel.svelte  우측 아티팩트 패널 — 탭 바(칩) + 활성 칩 콘텐츠 렌더링
  ArtifactImage.svelte  이미지 갤러리 — payload.items[] 기반, IntersectionObserver lazy load
  ArtifactChart.svelte  ECharts 그리드 — 페이지당 6개 페이지네이션, {#key page} remount
  ArtifactData.svelte   parquet 데이터 칩 패널 — GET /api/artifact/preview 로 head(10) 테이블
                        (횡 스크롤·sticky th·dtype 부기) + CSV 다운로드(showSaveFilePicker
                        저장 위치 선택, 미지원 시 앵커 다운로드 폴백)
  ChartCell.svelte      단일 ECharts 인스턴스 자가 관리 — onMount init·onDestroy dispose·ResizeObserver
  ArtifactLightbox.svelte  전체화면 확대 모달 — drag-to-resize 핸들(우하단), 좌우 키 네비게이션,
                           filter 툴바(brush Filter/Filter All/Undo/Redo/Reset + Legend 토글),
                           우측 레전드 편집 패널(드래그 순서·색상 스와치·눈 Hide·체크 Filter 선택)
```

## 상태($state) 패턴

`lib/state.svelte.js`의 `ui` 객체 하나가 전역 진실의 원천.

```js
// 읽기 — 컴포넌트 어디서나
import { ui } from "$lib/state.svelte.js";
ui.sessions;          // Session[]
ui.activeSessionId;
ui.streaming;         // 전송 중 여부 (입력 비활성 가드)
ui.nowTick;           // 생성 중 1초마다 갱신되는 클럭(ms) — TurnStatus 경과 시간 계산용
ui.theme;

// 현재 활성 프로바이더/모델 (ModelPicker 표시용)
ui.currentProvider;                    // "dtgpt" | "openai_compatible" | "mock"
ui.currentModel;                       // 현재 선택된 모델명
ui.modelListByProvider;                // { [provider]: { models, loading, loadedAt } }
ui.modelPickerOpen;                    // 드롭업 열림 여부

// 슬래시 커맨드
ui.availableSkills;                    // GET /api/skills 결과 캐시
ui.composerSkills;                     // 전송 시 force_skills 로 넘길 스킬 목록

// 아티팩트 패널
ui.activeArtifactId;
ui.artifactPanelOpen;
ui.artifactWidth;                      // 사용자 드래그 조절 패널 너비(px)

// 아티팩트 라이트박스
ui.lightbox.open;                      // boolean
ui.lightbox.kind;                      // "image" | "chart" | null
ui.lightbox.items;                     // 이미지 전용 payload.items[]
ui.lightbox.index;                     // 현재 보고 있는 항목 인덱스
ui.lightbox.chartKey;                  // 차트 전용 — ui.chartCache 의 키 (payload.src)
ui.lightbox.specPath;                  // 차트 전용 — 필터/레전드 API 에 전달할 spec 경로 (payload.spec)

// 차트 인터랙티브 캐시 (ArtifactChart·ArtifactLightbox 공유)
ui.chartCache;         // Record<src, { items, status, error, canUndo, canRedo }>
// chartCache 갱신 → 그리드(ArtifactChart)와 라이트박스(ArtifactLightbox) 동시 재렌더.

// 변형 — 반드시 액션 함수 경유
import { sendMessage, createSession } from "$lib/chatActions.svelte.js";
import { openSettings, saveSettings, openModelPicker, selectModel } from "$lib/settingsActions.svelte.js";
import {
  openLightbox, closeLightbox, lightboxNext, lightboxPrev,
  filterChartSelection, undoChartFilter, redoChartFilter, resetChartFilter,
  excludeLegend, setChartLegend,   // 레전드 Filter / 순서·색상·Hide
  artifactRefPath, insertArtifactReference,   // 칩→Composer 경로 참조 삽입
} from "$lib/artifactActions.svelte.js";
```

컴포넌트가 `ui.*`를 직접 write하는 것은 `SettingsModal` 내 draft 편집 필드만 허용한다 (`ui.settingsDraft.*`). 그 외는 전부 액션 함수가 담당.

## ModelPicker 컴포넌트

`Sidebar.svelte` 하단에 배치된 드롭업 피커. `settingsActions.svelte.js`의 액션 함수로만 제어한다.

- `openModelPicker()` — 피커 열기 + 현재 프로바이더 모델 목록 자동 로드 (5분 TTL 캐시)
- `loadModels(provider, { force })` — `GET /api/settings/models?provider=` 호출, `ui.modelListByProvider` 갱신
- `selectModel(modelId)` — `POST /api/settings { model }` 저장 + `ui.currentModel` 갱신 + 피커 닫기
- `closeModelPicker()` — backdrop 클릭 또는 Escape 시 호출

모델 목록이 5개 초과이면 검색 입력창이 자동 표시된다.

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

## 데이터 흐름 방향

로컬스토리지가 진실의 원천이다. 앱 시작 시 흐름은 **프론트 → 백엔드** (hydrate):

```
앱 마운트
  └─ initApp()
       ├─ localStorage 로드 → ui.sessions, ui.activeSessionId
       ├─ GET /api/app-info → ui.appName (앱 이름 동적 로드)
       ├─ GET /api/settings → ui.currentProvider, ui.currentModel
       ├─ openPresence(activeId)     // SSE 연결
       └─ restoreConversation(id, messages)  // POST /api/conversation/restore

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

## 서브에이전트 트레일 라우팅 (병렬 지원)

`chatActions.svelte.js` 가 `agent:switch` 수신 시 `subagent` 세그먼트를 push 하고,
`agent:progress`/`agent:return` 은 해당 트레일을 찾아 내부 segments 를 채우거나 done 으로 닫는다.

- `agent:switch` 세그먼트에 `dispatchId: ev.dispatch_id ?? null` 을 저장한다.
- 라우팅은 `_findSubagentForEvent(segments, ev)` 가 담당: **`ev.dispatch_id` 가 있으면 그
  상관키로 정확히 매칭**(병렬·같은 이름 동시 실행에도 충돌 없음), 없으면(구 세션·순차 폴백)
  `agentId` 기반 '마지막 running' 휴리스틱(`_findLastRunningSubagent`)으로 되돌아간다.
- 병렬(`call_sub_agents_parallel`)이면 한 메시지에 여러 `subagent` 세그먼트가 동시에 running
  상태로 쌓여 인터리브 진행된다. `call_sub_agents_parallel` 은 `_SENTINEL_TOOL_NAMES` 에
  포함돼 도구 카드로 중복 렌더되지 않는다.

## 생성 진행 상태 (TurnStatus)

`TurnStatus.svelte`는 assistant 메시지 버블 안, 세그먼트 타임라인 바로 뒤에 렌더된다.
`message.streaming === true` 인 동안만 표시되며, 세그먼트가 쌓인 후에도 계속 표시된다(기존 thinking dots와 다른 점).

- **펄스 점**: `var(--accent)` 색상, `pulse` 애니메이션
- **상황별 문구**: `message.segments` 트리를 검사해 동적으로 선택
  - running 상태 `tool` 세그먼트(서브에이전트 내부 포함) → `"도구 실행 중…"`
  - running 상태 `subagent` 세그먼트 → `"에이전트 작업 중…"`
  - 마지막 세그먼트가 `reasoning` → `"추론 중…"`
  - 그 외 → `"응답 생성 중…"`
- **경과 시간**: `elapsed = ui.nowTick - message.startedAt` — `ui.nowTick`이 1초마다 갱신되므로 `$derived`가 자동 재계산.

완료 후 `MessageBubble`은 `done-marker`(7px 회색 점)를 버블 상단에 표시하고, hover footer에 `formatDuration(message.durationMs)` 소요시간을 표시한다. ESC 중단 메시지는 `isStopped=true` 이므로 `done-marker` 표시 안 함.

### Svelte 5 reactive proxy 주의 (핵심)

`$state` 안의 객체는 Svelte가 reactive proxy로 래핑한다. `sendMessage()` 에서 `assistantMsg`를 plain object로 만들어 `session.messages`에 push한 뒤, `finally` 블록에서 `assistantMsg.streaming = false`로 직접 수정하면 **proxy를 우회**해 반응성이 트리거되지 않는다.

```js
// ❌ 잘못된 패턴 — plain object를 직접 수정 (reactive 아님)
const assistantMsg = { streaming: true, ... };
session.messages = [...session.messages, assistantMsg];
// ...나중에...
assistantMsg.streaming = false;  // proxy 우회, 화면 갱신 안 됨

// ✅ 올바른 패턴 — reactive proxy를 통해 수정 (stopStreaming과 동일)
const s = activeSession();
const msg = s?.messages.at(-1);
if (msg?.role === "assistant") msg.streaming = false;
```

`stopStreaming()`, `finally` 블록 등 streaming 관련 상태를 후속 설정할 때는 항상 `activeSession().messages.at(-1)` 경로를 사용한다.

## 차트 인터랙션 (ArtifactChart ↔ ArtifactLightbox)

`ui.chartCache[payload.src]`가 그리드와 라이트박스의 공유 진실 원천. 어느 쪽에서 액션을 해도 **양쪽이 동시 재렌더**된다.

```
ArtifactChart (그리드)        ArtifactLightbox (라이트박스)
       │                                │
       └─── ui.chartCache[src] ─────────┘
                     ↑ _applyChartFilter()가 POST /api/chart/filter 후
                       응답 items로 캐시 덮어씌움
```

### 라이트박스 툴바 컨트롤

**Filter 행 (brush / 레전드 그룹 선택):**
- brush 드래그 → `selectedRowIds` 채움 → **Filter** / **Filter All** 버튼 활성 → `filterChartSelection(scope, idx, rowIds)`
- 레전드 패널에서 체크박스 선택 → `selectedLegend` 채움 → 같은 **Filter** / **Filter All** 버튼 → `excludeLegend(scope, idx, names)`
- 두 선택이 동시에 있으면 레전드 선택이 우선.
- **Undo** / **Redo** / **Reset** — ViewState 스택 cursor 조작, 동작 종류 무관하게 동작.

**Legend 버튼** (color 채널 있는 차트, 레전드 2개 이상일 때만 활성):
- 클릭 → 라이트박스 우측에 240px 패널 토글.
- 패널 상태는 `current.option` 단일 소스에서 파생(`legendNames`, `legendColors`, `hiddenSet`).
- 드래그 재배치 → `setChartLegend(idx, { order })` / 컬러피커 → `setChartLegend(idx, { colors })` / 눈 → `setChartLegend(idx, { hidden })`.

### Material Symbols 폰트 서브셋 (`index.html`)

사용 아이콘: `drag_indicator, redo, refresh, undo, visibility, visibility_off`.  
**새 아이콘을 사용할 때** 반드시 `index.html`의 `&icon_names=` 파라미터에 추가해야 한다. 누락 시 ligature 텍스트(글자 그대로)로 렌더된다.

## 칩→Composer 참조 삽입

아티팩트 칩(메시지 버블)과 패널 헤더에 보조 버튼이 있어, 산출물의 `result/...` 경로를 입력창에 삽입한다 — "이 산출물로 작업해줘" 류 후속 요청을 클릭으로 지정하는 UX. 백엔드 `load_artifact`/`display_*` 가 그대로 해석하는 경로이므로 [backend_architecture.md](backend_architecture.md)의 산출물 재발견 도구와 직결된다.

- `artifactRefPath(chip)` — 칩 종류별 참조 경로 환원: chart는 `payload.spec`(이미 `result/...`; parquet 은 spec 의 `data.source` 로 연계 발견되므로 spec 하나가 인용 단위), markdown은 `/result/...` URL → `result/...`, data는 `payload.path` 그대로. image는 **인용 가능한 모든 items 경로를 줄바꿈으로 이어 반환** (다중 이미지 갤러리 전체 인용; 경로에 공백이 들어갈 수 있어 공백 구분은 모호). data URI·외부 URL·workspace/assets 는 제외, 인용 가능한 경로가 하나도 없으면 `null` → 버튼 숨김.
- `insertArtifactReference(chipId)` — `ui.composerSeed` 에 경로를 써넣는다. `MessageBubble` 의 칩은 `event.stopPropagation()` 으로 패널 열기(`openArtifact`)와 분리한 별도 `@` 버튼, `ArtifactPanel` 은 헤더의 `@ 참조` 버튼.
- **Composer seed 는 replace→append 로 변경됨**: `value ? value.trimEnd() + " " + seed : seed`. 기존 입력 뒤에 공백으로 이어 붙는다. `rewindToMessage` 는 빈 composer 에서 발동하므로 동작 불변.

## 데이터 칩 (kind: "data") — parquet 중간 산출물 인용

전처리 중간 데이터(parquet)가 디스크에 저장될 때 칩을 만들어 후속 턴에서 인용할 수 있게 한다.

- **생성 경로** (`chatActions.svelte.js` `_dataArtifactPayloads`): ① `save_artifact` 성공 + `data.kind === "parquet"` → payload `{path, filename, size, rows, columns}`. ② `exec_code` 결과의 `data.new_artifacts[]` 중 parquet → `{path, filename, size}` (rows/cols 는 패널 preview fetch 가 보충). parquet 만 칩이 된다 — 중간 데이터 영속 포맷 통일 방향.
- **자동 오픈 없음**: display_* 칩과 달리 패널을 열지 않는다 (`addChip(..., { open: false })`) — 전처리 중 빈번한 중간 저장마다 패널이 튀는 것을 방지.
- **패널 콘텐츠**: `ArtifactData.svelte` 가 `GET /api/artifact/preview` 로 head(10) 테이블 + 메타(rows×cols·size·경로)를 렌더. CSV 버튼은 `GET /api/artifact/csv` 를 showSaveFilePicker(저장 위치 선택) 또는 앵커 다운로드로 저장.
- 패널 리사이즈 상한 `ARTIFACT_WIDTH_MAX = 1000` (storage.js) — 와이드 테이블 대응. viewport 60% 캡은 별도 유지.

## 테마 시스템

`app.css`의 `:root` / `[data-theme="dark"]` CSS 변수 토큰 기반.
`setTheme(theme)`이 `document.documentElement.setAttribute("data-theme", theme)` 호출.
컴포넌트 scoped CSS에서는 `[data-theme="dark"]` 셀렉터를 쓸 수 없음 — 색상값은 반드시 CSS 변수(`var(--color-success)` 등)로 정의하고 `app.css`에서 테마별 분기.
