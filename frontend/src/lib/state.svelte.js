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
});

export function activeSession() {
  return ui.sessions.find((s) => s.id === ui.activeSessionId) ?? null;
}
