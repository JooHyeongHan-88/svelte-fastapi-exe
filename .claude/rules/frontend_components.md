# 프론트엔드 컴포넌트 · UI 패턴

`frontend_architecture.md` 에서 발췌. 컴포넌트 카탈로그 · TurnStatus · 서브에이전트
트레일 라우팅 · 차트 인터랙션 UI · 칩->Composer · 데이터 칩 · 테마를 다룬다.

상태·데이터 흐름·localStorage 스키마는 [frontend_state.md](frontend_state.md) 참고.

---

## 파일 책임 분리

```
lib/
  state.svelte.js       전역 $state 객체 ui + activeSession()·isEmptySession() 헬퍼
  chatActions.svelte.js 세션·메시지 액션 + presence + 업데이트 + 초기화
  settingsActions.svelte.js LLM 설정 모달 + ModelPicker 액션 (열기/닫기/저장/테스트/모델로드)
  api.js                fetch 래퍼 - 컴포넌트는 URL을 직접 모름
  settingsApi.js        설정 관련 fetch 래퍼 (/api/settings/*, /api/app-info)
  sse.js                parseSseStream(body, onEvent) - SSE 파싱
  storage.js            localStorage CRUD (세션, activeId, 테마)
  markdown.js           renderMarkdown(text) - marked + DOMPurify + hljs
  format.js             autoTitle, relativeTimeBucket, formatElapsed, formatDuration
  evaluatorBridge.svelte.js  evaluator 확장 탭의 BroadcastChannel("evaluator:exports")
                        구독 - 내보내기 알림 시 해당 세션 마지막 어시스턴트 메시지에
                        parquet 데이터 칩 부착(initApp 시작·teardown 정리). 별도 탭이라
                        SSE 가 아닌 BroadcastChannel 경유 (-> extensions_evaluator.md)

components/
  Sidebar.svelte        세션 목록 + 새 대화 버튼 + 테마 토글 + 설정 아이콘 + ModelPicker
                        + 데스크탑 접기 버튼(.collapse-btn → toggleSidebarCollapsed, 폭 0 완전 숨김,
                        ui.sidebarCollapsed 영속). 펼치기는 TopBar .sidebar-expand
  SessionItem.svelte    세션 행 (클릭=선택, 더블클릭=인라인 rename, hover=삭제)
  ChatArea.svelte       메시지 스크롤 영역, 하단 자동 스크롤 + 빈 세션 히어로
                        (Logo 스파크 + 시간대별 세리프 인사말 - App.svelte 의 hero-spacer 와
                        합쳐 인사말+컴포저 쌍을 중앙 부근에 배치, isEmptySession() 공유)
  MessageBubble.svelte  user(plain text) / assistant(markdown) 버블 + 완료 표식
  Composer.svelte       auto-resize textarea, Enter=전송 / Shift+Enter=줄바꿈
  TopBar.svelte         현재 세션 제목, 모바일 사이드바 토글 + 데스크탑 사이드바 펼치기
                        버튼(.sidebar-expand, ui.sidebarCollapsed 일 때만 노출)
  ModelPicker.svelte    사이드바 하단 프로바이더/모델 표시 + 빠른 모델 전환 드롭업
  SettingsModal.svelte  LLM 설정 모달 (프로바이더·모델·API키·Base URL)
  UpdateBanner.svelte   업데이트 알림 배너
  UpdateModal.svelte    업데이트 진행 모달
  TurnStatus.svelte     생성 중 진행 표식 - 펄스 점 + 상황별 문구 + 경과 시간
  ArtifactPanel.svelte  우측 아티팩트 패널 - 탭 바(칩) + 활성 칩 콘텐츠 렌더링
                        + 헤더 '최대화' 버튼(패널-레벨, 모든 kind 공용 → toggleArtifactMaximize).
                        최대화 시 헤더·탭·핸들 숨기고 본문을 뷰포트 전체로(.maximized: fixed/inset 0/
                        z 60, 라이트박스 9999 아래). 복귀는 본문 위 떠 있는 .restore-btn(평소 옅게·
                        hover/진입 hint 또렷, ESC 미지원). ui.artifactMaximized(휘발, 닫으면 리셋)
  ArtifactImage.svelte  이미지 갤러리 - payload.items[] 기반, IntersectionObserver lazy load
  ArtifactChart.svelte  ECharts 그리드 - 페이지당 12개 페이지네이션, {#key page} remount
  ArtifactData.svelte   parquet 데이터 칩 패널 - GET /api/artifact/preview 로 head(10) 테이블
                        (횡 스크롤·sticky th·dtype 부기) + CSV 다운로드(showSaveFilePicker
                        저장 위치 선택, 미지원 시 앵커 다운로드 폴백)
  ArtifactExtension.svelte 확장(extension) 칩 패널 - 확장 SPA 를 same-origin <iframe src=/ext/<tool>/...>
                        로 임베드(헤더 없음, iframe 만). src 에 ?theme=<현재> 1회 부착(untrack,
                        라이브 변경은 BroadcastChannel("app:theme")). open_curation 칩·런처 뷰 공용
  ExtensionMenu.svelte  TopBar 패널-열기 버튼 옆 caret 드롭다운 - ui.extensions(/api/extensions) 나열,
                        고르면 openExtensionPanel(tool)로 확장을 패널에 휘발 뷰로 연다(ModelPicker 패턴)
  ChartCell.svelte      단일 ECharts 인스턴스 자가 관리 - onMount init·onDestroy dispose·ResizeObserver
  ArtifactLightbox.svelte  전체화면 확대 모달 - drag-to-resize 핸들(우하단), 좌우 키 네비게이션,
                           filter 툴바(brush Filter/Filter All/Undo/Redo/Reset + Legend 토글),
                           우측 레전드 편집 패널(드래그 순서·색상 스와치·눈 Hide·체크 Filter 선택)
  Logo.svelte           브랜드 마크 (message-circle SVG, 액센트색) - 사이드바 헤더·빈 세션 히어로 공용
  ArtifactIcon.svelte   아티팩트 종류별 인라인 SVG 아이콘 (image/chart/markdown/data/file 폴백)
                        - 칩·패널 헤더·탭의 이모지 대체 (오프라인 안전, currentColor 상속)
```

---

## ModelPicker 컴포넌트

`Sidebar.svelte` 하단에 배치된 드롭업 피커. `settingsActions.svelte.js`의 액션 함수로만 제어한다.

- `openModelPicker()` - 피커 열기 + 현재 프로바이더 모델 목록 자동 로드 (5분 TTL 캐시)
- `loadModels(provider, { force })` - `GET /api/settings/models?provider=` 호출, `ui.modelListByProvider` 갱신
- `selectModel(modelId)` - `POST /api/settings { model }` 저장 + `ui.currentModel` 갱신 + 피커 닫기
- `closeModelPicker()` - backdrop 클릭 또는 Escape 시 호출

모델 목록이 5개 초과이면 검색 입력창이 자동 표시된다.

---

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

---

## 생성 진행 상태 (TurnStatus)

`TurnStatus.svelte`는 assistant 메시지 버블 안, 세그먼트 타임라인 바로 뒤에 렌더된다.
`message.streaming === true` 인 동안만 표시되며, 세그먼트가 쌓인 후에도 계속 표시된다.

- **펄스 점**: `var(--accent)` 색상, `pulse` 애니메이션
- **상황별 문구**: `message.segments` 트리를 검사해 동적으로 선택
  - running 상태 `tool` 세그먼트(서브에이전트 내부 포함) -> `"도구 실행 중..."`
  - running 상태 `subagent` 세그먼트 -> `"에이전트 작업 중..."`
  - 마지막 세그먼트가 `reasoning` -> `"추론 중..."`
  - 그 외 -> `"응답 생성 중..."`
- **경과 시간**: `elapsed = ui.nowTick - message.startedAt` - `ui.nowTick`이 1초마다 갱신되므로 `$derived`가 자동 재계산.

완료 후 `MessageBubble`은 `done-marker`(7px 회색 점)를 버블 상단에 표시하고, hover footer에 `formatDuration(message.durationMs)` 소요시간을 표시한다. ESC 중단 메시지는 `isStopped=true` 이므로 `done-marker` 표시 안 함.

---

## 차트 인터랙션 (ArtifactChart <-> ArtifactLightbox)

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
- brush 드래그 -> `selectedRowIds` 채움 -> **Filter** / **Filter All** 버튼 활성 -> `filterChartSelection(scope, idx, rowIds)`
- 레전드 패널에서 체크박스 선택 -> `selectedLegend` 채움 -> 같은 **Filter** / **Filter All** 버튼 -> `excludeLegend(scope, idx, names)`
- 두 선택이 동시에 있으면 레전드 선택이 우선.
- **Undo** / **Redo** / **Reset** - ViewState 스택 cursor 조작, 동작 종류 무관하게 동작.

**Legend 버튼** (color 채널 있는 차트, 레전드 2개 이상일 때만 활성):
- 클릭 -> 라이트박스 우측에 240px 패널 토글.
- 패널 상태는 `current.option` 단일 소스에서 파생(`legendNames`, `legendColors`, `hiddenSet`).
- 드래그 재배치 -> `setChartLegend(idx, { order })` / 컬러피커 -> `setChartLegend(idx, { colors })` / 눈 -> `setChartLegend(idx, { hidden })`.

### Material Symbols 폰트 서브셋 (`index.html`)

사용 아이콘: `drag_indicator, redo, refresh, undo, visibility, visibility_off`.
**새 아이콘을 사용할 때** 반드시 `index.html`의 `&icon_names=` 파라미터에 추가해야 한다. 누락 시 ligature 텍스트(글자 그대로)로 렌더된다.

---

## 칩->Composer 참조 삽입

아티팩트 칩(메시지 버블)과 패널 헤더에 보조 버튼이 있어, 산출물의 `result/...` 경로를 입력창에 삽입한다.
백엔드 `load_artifact`/`display_*` 가 그대로 해석하는 경로이므로 [agent_runtime.md](agent_runtime.md)의 산출물 재발견 도구와 직결된다.

- `artifactRefPath(chip)` - 칩 종류별 참조 경로 환원: chart는 `payload.spec`(이미 `result/...`; parquet 은 spec 의 `data.source` 로 연계 발견되므로 spec 하나가 인용 단위), markdown은 `/result/...` URL -> `result/...`, data는 `payload.path` 그대로. image는 **인용 가능한 모든 items 경로를 줄바꿈으로 이어 반환** (다중 이미지 갤러리 전체 인용). data URI·외부 URL·workspace/assets 는 제외, 인용 가능한 경로가 하나도 없으면 `null` -> 버튼 숨김.
- `insertArtifactReference(chipId)` - `ui.composerSeed` 에 경로를 써넣는다. Composer seed 는 **replace->append**: `value ? value.trimEnd() + " " + seed : seed`. 기존 입력 뒤에 공백으로 이어 붙는다.
- `revealArtifactFolder(chipId)` - 패널 헤더 '폴더 열기' 버튼. 참조 경로의 **고유 폴더마다** `POST /api/artifact/reveal` 1회. 전부 성공 시 `true` 반환; 실패하면 `ArtifactPanel` 이 버튼을 2.4s 적색 플래시(`--danger`)+툴팁 교체로 피드백한다.

---

## 데이터 칩 (kind: "data") - parquet 중간 산출물 인용

전처리 중간 데이터(parquet)가 디스크에 저장될 때 칩을 만들어 후속 턴에서 인용할 수 있게 한다.

- **생성 경로** (`chatActions.svelte.js` `_dataArtifactPayloads`): ① `save_artifact` 성공 + `data.kind === "parquet"` -> payload `{path, filename, size, rows, columns}`. ② `exec_code` 결과의 `data.new_artifacts[]` 중 parquet -> `{path, filename, size}` (rows/cols 는 패널 preview fetch 가 보충). parquet 만 칩이 된다.
- **자동 오픈 없음**: display_* 칩과 달리 패널을 열지 않는다 (`addChip(..., { open: false })`) - 전처리 중 빈번한 중간 저장마다 패널이 튀는 것을 방지.
- **패널 콘텐츠**: `ArtifactData.svelte` 가 `GET /api/artifact/preview` 로 head(10) 테이블 + 메타(rows x cols·size·경로)를 렌더. CSV 버튼은 `GET /api/artifact/csv` 를 showSaveFilePicker(저장 위치 선택) 또는 앵커 다운로드로 저장.
- 패널 리사이즈 상한 `ARTIFACT_WIDTH_MAX = 1000` (storage.js) - 와이드 테이블 대응. viewport 60% 캡은 별도 유지.

---

## 테마 시스템

`app.css`의 `:root` / `[data-theme="dark"]` CSS 변수 토큰 기반.
`setTheme(theme)`이 `document.documentElement.setAttribute("data-theme", theme)` 호출.
컴포넌트 scoped CSS에서는 `[data-theme="dark"]` 셀렉터를 쓸 수 없음 - 색상값은 반드시 CSS 변수(`var(--color-success)` 등)로 정의하고 `app.css`에서 테마별 분기.

팔레트는 웜 뉴트럴 + 테라코타 액센트 (Claude Desktop 벤치마킹). 주요 토큰 군:

- 색: `--bg/--bg-elevated/--bg-hover/--bg-active`, `--fg/-muted/-subtle`, `--accent(-hover/-fg)`, `--danger(-bg)`, `--color-success`, `--backdrop`(오버레이 통일)
- 액센트 틴트: `--accent-soft`(10%)·`--accent-soft-strong`(18%)·`--accent-border`(30%) - `:root` 1회 선언으로 양 테마 대응. 컴포넌트에서 일회성 `color-mix(accent N%)` 작성 금지, 이 토큰을 쓸 것
- 포커스: `--focus-ring` (input/textarea box-shadow 공용) + 글로벌 `:where(...):focus-visible` outline (0-특이성이라 컴포넌트 스타일이 항상 이김)
- radius: `--radius-sm`(8) / `--radius-md`(12) / `--radius-lg`(16) / `--radius-full`(필) - 하드코딩 px 금지
- duration: `--dur-fast`(0.12s, 마이크로 인터랙션) / `--dur-slow`(0.18s, 패널·슬라이드)
- 타이포: `--font-display` 세리프 (Noto Serif KR CDN, 오프라인 시 Georgia/Batang 폴백) - 빈 세션 인사말 + `.markdown` h1/h2 전용. 채팅 본문(`.markdown`·user-content·composer textarea)은 15px, UI 크롬은 14px 유지
