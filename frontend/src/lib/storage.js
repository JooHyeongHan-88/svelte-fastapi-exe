// localStorage 가 진실의 원천. 모든 IO 는 이 모듈을 경유.

const KEY_SESSIONS = "chat:sessions:v1";
const KEY_ACTIVE = "chat:activeSessionId:v1";
const KEY_THEME = "chat:theme:v1";
const KEY_ARTIFACT_WIDTH = "chat:artifactWidth:v1";

const ARTIFACT_WIDTH_MIN = 320;
const ARTIFACT_WIDTH_MAX = 800;
const ARTIFACT_WIDTH_DEFAULT = 420;

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
