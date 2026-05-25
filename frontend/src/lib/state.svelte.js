// 전역 reactive 상태 (Svelte 5 runes). 컴포넌트는 ui 를 직접 import 해서 읽고,
// 변형은 chatActions 의 함수들로만 수행한다.

export const ui = $state({
  sessions: [],
  activeSessionId: null,
  streaming: false,
  theme: "light",
  sidebarOpen: false,

  updateInfo: null,
  updateDismissed: false,
  modalOpen: false,
  applying: false,
  applyState: null,
  restarting: false,

  // Settings modal
  settingsOpen: false,
  /** @type {null | { provider, model, api_key, _maskedKey, base_url, temperature, max_tokens, system_prompt, clearKey }} */
  settingsDraft: null,
  settingsSaving: false,
  settingsError: null,
  settingsTesting: false,
  /** @type {null | { ok: boolean, message: string, latency_ms?: number }} */
  settingsTestResult: null,
  /** @type {Array<{ id, label, requires_api_key, requires_base_url, requires_model, suggested_models, docs_url }>} */
  providers: [],

  // 슬래시 커맨드용 — 부팅 시 GET /api/skills 결과 캐시.
  /** @type {Array<{ name: string, description: string, trigger: string[], priority: number }>} */
  availableSkills: [],
  // 현재 Composer 에 부착된 skill 이름 목록 (전송 시 force_skills 로 백엔드 전달, 직후 리셋).
  /** @type {string[]} */
  composerSkills: [],

  // 아티팩트 패널 — display_image / display_chart 도구 결과 누적
  /**
   * @type {Array<{
   *   id: string,
   *   kind: "image"|"chart",
   *   payload: object,
   *   label: string,
   *   sourceMessageId: string|null,
   *   createdAt: number
   * }>}
   */
  artifacts: [],
  activeArtifactId: /** @type {string|null} */ (null),
  artifactPanelOpen: false,
});

export function activeSession() {
  return ui.sessions.find((s) => s.id === ui.activeSessionId) ?? null;
}
