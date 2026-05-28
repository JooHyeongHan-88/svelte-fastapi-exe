// localStorage 가 진실의 원천. 모든 IO 는 이 모듈을 경유.

const KEY_SESSIONS = "chat:sessions:v1";
const KEY_ACTIVE = "chat:activeSessionId:v1";
const KEY_THEME = "chat:theme:v1";
const KEY_ARTIFACT_WIDTH = "chat:artifactWidth:v1";
const KEY_ARTIFACT_PANEL_OPEN = "chat:artifactPanelOpen:v1";
const KEY_SIDEBAR_WIDTH = "chat:sidebarWidth:v1";

const ARTIFACT_WIDTH_MIN = 320;
const ARTIFACT_WIDTH_MAX = 800;
const ARTIFACT_WIDTH_DEFAULT = 420;

const SIDEBAR_WIDTH_MIN = 180;
const SIDEBAR_WIDTH_MAX = 480;
const SIDEBAR_WIDTH_DEFAULT = 264;

export function loadSessions() {
  try {
    const raw = localStorage.getItem(KEY_SESSIONS);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveSessions(sessions) {
  try {
    localStorage.setItem(KEY_SESSIONS, JSON.stringify(sessions));
  } catch {
    // QuotaExceededError 가능 — UX 차원에서 사용자에게 알리는 건 추후 과제.
  }
}

export function loadActiveId() {
  try {
    return localStorage.getItem(KEY_ACTIVE);
  } catch {
    return null;
  }
}

export function saveActiveId(id) {
  try {
    if (id) localStorage.setItem(KEY_ACTIVE, id);
    else localStorage.removeItem(KEY_ACTIVE);
  } catch {}
}

export function loadTheme() {
  try {
    const t = localStorage.getItem(KEY_THEME);
    return t === "dark" || t === "light" ? t : "light";
  } catch {
    return "light";
  }
}

export function saveTheme(theme) {
  try {
    localStorage.setItem(KEY_THEME, theme);
  } catch {}
}

export function loadArtifactWidth() {
  try {
    const raw = localStorage.getItem(KEY_ARTIFACT_WIDTH);
    if (!raw) return ARTIFACT_WIDTH_DEFAULT;
    const n = Number(raw);
    if (!Number.isFinite(n)) return ARTIFACT_WIDTH_DEFAULT;
    return Math.min(ARTIFACT_WIDTH_MAX, Math.max(ARTIFACT_WIDTH_MIN, n));
  } catch {
    return ARTIFACT_WIDTH_DEFAULT;
  }
}

export function saveArtifactWidth(px) {
  try {
    const clamped = Math.min(
      ARTIFACT_WIDTH_MAX,
      Math.max(ARTIFACT_WIDTH_MIN, Math.round(px)),
    );
    localStorage.setItem(KEY_ARTIFACT_WIDTH, String(clamped));
  } catch {}
}

export const ARTIFACT_WIDTH_BOUNDS = {
  min: ARTIFACT_WIDTH_MIN,
  max: ARTIFACT_WIDTH_MAX,
  default: ARTIFACT_WIDTH_DEFAULT,
};

// 아티팩트 패널 열림 상태를 영속화. TopBar 토글 버튼이 sticky 한 UX 를 제공하려면
// 새로고침 / 세션 전환 후에도 마지막 상태를 복원할 필요가 있다.
export function loadArtifactPanelOpen() {
  try {
    return localStorage.getItem(KEY_ARTIFACT_PANEL_OPEN) === "1";
  } catch {
    return false;
  }
}

export function saveArtifactPanelOpen(open) {
  try {
    localStorage.setItem(KEY_ARTIFACT_PANEL_OPEN, open ? "1" : "0");
  } catch {}
}

export function loadSidebarWidth() {
  try {
    const raw = localStorage.getItem(KEY_SIDEBAR_WIDTH);
    if (!raw) return SIDEBAR_WIDTH_DEFAULT;
    const n = Number(raw);
    if (!Number.isFinite(n)) return SIDEBAR_WIDTH_DEFAULT;
    return Math.min(SIDEBAR_WIDTH_MAX, Math.max(SIDEBAR_WIDTH_MIN, n));
  } catch {
    return SIDEBAR_WIDTH_DEFAULT;
  }
}

export function saveSidebarWidth(px) {
  try {
    const clamped = Math.min(
      SIDEBAR_WIDTH_MAX,
      Math.max(SIDEBAR_WIDTH_MIN, Math.round(px)),
    );
    localStorage.setItem(KEY_SIDEBAR_WIDTH, String(clamped));
  } catch {}
}

export const SIDEBAR_WIDTH_BOUNDS = {
  min: SIDEBAR_WIDTH_MIN,
  max: SIDEBAR_WIDTH_MAX,
  default: SIDEBAR_WIDTH_DEFAULT,
};
