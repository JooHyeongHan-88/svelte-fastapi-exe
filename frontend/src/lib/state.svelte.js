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
});

export function activeSession() {
  return ui.sessions.find((s) => s.id === ui.activeSessionId) ?? null;
}
