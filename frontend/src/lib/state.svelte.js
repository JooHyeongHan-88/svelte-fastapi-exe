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

  // Composer textarea 에 외부에서 텍스트를 주입하기 위한 일회용 슬롯.
  // rewindToMessage() 가 잘라낸 user 메시지 본문을 여기에 쓰면 Composer 가
  // $effect 로 감지해 value 에 복사 후 즉시 비워진다.
  composerSeed: "",

  // 아티팩트 패널 — 활성 칩 id 와 패널 가시성만 휘발 상태로 둔다.
  // 산출물 payload 는 메시지 안 (message.artifactChips[].payload) 에 영속.
  activeArtifactId: /** @type {string|null} */ (null),
  artifactPanelOpen: false,

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
