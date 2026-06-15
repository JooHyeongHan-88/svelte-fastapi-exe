// 전역 reactive 상태 (Svelte 5 runes). 컴포넌트는 ui 를 직접 import 해서 읽고,
// 변형은 chatActions 의 함수들로만 수행한다.

export const ui = $state({
  sessions: [],
  activeSessionId: null,
  streaming: false,
  // 생성 중일 때만 1초마다 갱신되는 reactive 클럭 (ms). TurnStatus 컴포넌트가 경과 시간 계산에 사용.
  nowTick: 0,
  theme: "light",
  sidebarOpen: false,
  appName: "MyAgent",
  appVersion: "",

  updateInfo: null,
  updateDismissed: false,
  modalOpen: false,
  applying: false,
  applyState: null,
  restarting: false,

  // Settings modal
  settingsOpen: false,
  /** @type {null | { provider: string, cache: Record<string, { model, api_key, _maskedKey, base_url, clearKey }> }} */
  settingsDraft: null,
  settingsSaving: false,
  settingsError: null,
  settingsTesting: false,
  /** @type {null | { ok: boolean, message: string, latency_ms?: number }} */
  settingsTestResult: null,
  /** @type {Array<{ id, label, requires_api_key, requires_base_url, requires_model, suggested_models, docs_url }>} */
  providers: [],

  // 현재 활성 provider / model — 사이드바 ModelPicker 에 표시
  currentProvider: "",
  currentModel: "",
  /** @type {Record<string, { models: string[], loading: boolean, loadedAt: number }>} */
  modelListByProvider: {},
  modelPickerOpen: false,

  // 슬래시 커맨드용 — 부팅 시 GET /api/skills 결과 캐시.
  /** @type {Array<{ name: string, description: string, trigger: string[], priority: number }>} */
  availableSkills: [],
  // 현재 Composer 에 부착된 skill 이름 목록 (전송 시 force_skills 로 백엔드 전달, 직후 리셋).
  /** @type {string[]} */
  composerSkills: [],

  // 입력창(contenteditable)에 커서 위치로 산출물 인용 pill 을 삽입하라는 일회용 신호.
  // artifactActions.insertArtifactReference 가 채우면 Composer 의 $effect 가 소비 후 null 로 비운다.
  // nonce 로 같은 파일을 연속 삽입해도 매번 감지되게 한다.
  /** @type {null | { items: Array<{ path: string, label: string }>, nonce: number }} */
  composerInsertRef: null,

  // 입력창 내용을 parts 로 통째 재구성하라는 일회용 신호 (rewindToMessage 가 되돌린 시점 복원).
  /** @type {null | { parts: Array<{ type: "text"|"ref", value?: string, path?: string, label?: string }>, nonce: number }} */
  composerSetParts: null,

  // 아티팩트 패널 — 활성 칩 id 와 패널 가시성만 휘발 상태로 둔다.
  // 산출물 payload 는 메시지 안 (message.artifactChips[].payload) 에 영속.
  activeArtifactId: /** @type {string|null} */ (null),
  artifactPanelOpen: false,

  // 확장(extensions) 런처 — 패널 열기 버튼의 드롭다운이 띄울 수 있는 확장 카탈로그.
  // GET /api/extensions 결과를 부팅 시 1회 캐시한다.
  /** @type {Array<{ tool: string, name: string, description: string, icon: string }>} */
  extensions: [],
  extensionMenuOpen: false,
  // 드롭다운으로 직접 연 확장은 대화 산출물이 아니므로 휘발 뷰로 둔다(메시지 칩과 별개).
  // open_curation 이 만든 확장 칩은 메시지에 영속되지만, 이 뷰는 단일·비영속이다.
  /** @type {null | { id: string, kind: "extension", label: string, payload: { tool: string, src: string, title: string } }} */
  extensionView: null,

  // 세션별 산출물 총 용량 — { client_id[:8]: bytes }. 사이드바 SessionItem 이
  // 세션 id 앞 8자로 조회해 작고 연한 텍스트로 표시한다. refreshArtifactUsage() 가 갱신.
  /** @type {Record<string, number>} */
  artifactUsage: {},

  // 사용자가 마우스 드래그로 조절한 우측 아티팩트 패널 너비 (px). initApp 에서 로드.
  artifactWidth: 420,

  // 사용자가 마우스 드래그로 조절한 좌측 사이드바 너비 (px). initApp 에서 로드.
  sidebarWidth: 264,

  // 아티팩트 라이트박스 — 이미지·차트 셀 클릭 시 리사이즈 가능한 모달로 확대 표시.
  // items 는 이미지 전용. 차트는 chartCache 를 통해 읽어 필터 반영을 단일 소스로 관리.
  /** @type {{ open: boolean, kind: "image"|"chart"|null, items: any[], index: number, chartKey: string|null, specPath: string|null }} */
  lightbox: {
    open: false,
    kind: null,
    items: [],   // 이미지 전용
    index: 0,
    chartKey: null,   // 차트 전용 — ui.chartCache 의 키 (payload.src)
    specPath: null,   // 차트 전용 — 필터 API 에 전달할 spec 경로 (payload.spec)
  },

  // 차트 인터랙티브 필터 캐시.
  // ArtifactChart 가 fetch 해 채우고, 필터 액션이 항목을 갱신한다.
  // ArtifactChart(그리드)와 ArtifactLightbox(모달)가 동일 항목을 참조해
  // 필터 결과가 양쪽에 동시 반영된다.
  /** @type {Record<string, { items: any[], status: "loading"|"ok"|"error", error: string, canUndo: boolean, canRedo: boolean }>} */
  chartCache: {},
});

export function activeSession() {
  return ui.sessions.find((s) => s.id === ui.activeSessionId) ?? null;
}

// 빈 세션(메시지 0개 · 생성 중 아님) 여부 — ChatArea 히어로 블록과 App 의
// hero-spacer 가 공유하는 단일 조건. sendMessage 가 메시지를 동기 push 하므로
// 전송 즉시 false 로 떨어진다 (streaming 체크는 belt-and-suspenders).
export function isEmptySession() {
  return (activeSession()?.messages ?? []).length === 0 && !ui.streaming;
}
