// 세션/메시지 액션. UI 는 이 함수들만 호출하고, localStorage 와 백엔드 sync 는 여기서 책임진다.

import { ui, activeSession } from "./state.svelte.js";
import {
  loadSessions,
  saveSessions,
  loadActiveId,
  saveActiveId,
  loadTheme,
  saveTheme,
} from "./storage.js";
import {
  chat,
  deleteConversation,
  restoreConversation,
  checkUpdate,
  applyUpdate,
  getUpdateStatus,
} from "./api.js";
import { parseSseStream } from "./sse.js";
import { autoTitle } from "./format.js";

const SAVE_DEBOUNCE_MS = 200;
const UPDATE_POLL_MS = 500;

let presenceSource = null;
let saveTimer = null;

// ---------- 영속화 ----------

function scheduleSave() {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    saveSessions(ui.sessions);
    saveTimer = null;
  }, SAVE_DEBOUNCE_MS);
}

function flushSave() {
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
  saveSessions(ui.sessions);
}

// ---------- presence (활성 세션의 client_id 로만 1개 유지) ----------

function openPresence(clientId) {
  closePresence();
  // EventSource 단일 채널 = 생존 신호. 백엔드 watchdog 이 끊김을 감지하면 자동 정리.
  presenceSource = new EventSource(`/api/presence?client_id=${clientId}`);
}

function closePresence() {
  if (presenceSource) {
    presenceSource.close();
    presenceSource = null;
  }
}

// ---------- 세션 ----------

function newSession() {
  const now = Date.now();
  return {
    id: crypto.randomUUID(),
    title: "새 대화",
    titleEdited: false,
    createdAt: now,
    updatedAt: now,
    messages: [],
  };
}

function toBackendMessages(uiMessages) {
  // UI 모델 → backend Message 스키마. toolStatus/id/createdAt 은 백엔드에 보내지 않음.
  return uiMessages.map((m) => ({ role: m.role, content: m.content }));
}

export async function createSession() {
  if (ui.streaming) return;

  const session = newSession();
  ui.sessions = [session, ...ui.sessions];
  ui.activeSessionId = session.id;
  saveActiveId(session.id);
  flushSave();

  openPresence(session.id);
  // 새 세션은 백엔드 store 도 빈 상태로 시작 — restore 는 호출 안 함.
}

export async function selectSession(id) {
  if (ui.streaming) return;
  if (id === ui.activeSessionId) return;

  const target = ui.sessions.find((s) => s.id === id);
  if (!target) return;

  ui.activeSessionId = id;
  saveActiveId(id);

  openPresence(id);
  // EXE 재시작 등으로 백엔드 context 가 비어있을 수 있으므로 매 선택마다 다시 주입.
  await restoreConversation(id, toBackendMessages(target.messages));
}

export async function deleteSession(id) {
  if (ui.streaming) return;

  const idx = ui.sessions.findIndex((s) => s.id === id);
  if (idx === -1) return;

  ui.sessions = ui.sessions.filter((s) => s.id !== id);
  await deleteConversation(id);

  if (ui.activeSessionId === id) {
    const next = ui.sessions[0] ?? null;
    ui.activeSessionId = next?.id ?? null;
    saveActiveId(ui.activeSessionId);

    if (next) {
      openPresence(next.id);
      await restoreConversation(next.id, toBackendMessages(next.messages));
    } else {
      closePresence();
    }
  }

  flushSave();
}

export function renameSession(id, newTitle) {
  const trimmed = (newTitle ?? "").trim();
  if (!trimmed) return;

  const session = ui.sessions.find((s) => s.id === id);
  if (!session) return;

  session.title = trimmed;
  session.titleEdited = true;
  session.updatedAt = Date.now();
  ui.sessions = [...ui.sessions];
  flushSave();
}

// ---------- 메시지 전송 ----------

export async function sendMessage(text) {
  const content = text.trim();
  if (!content || ui.streaming) return;

  // 활성 세션이 없으면 즉석 생성 (첫 메시지 시나리오).
  if (!ui.activeSessionId) {
    await createSession();
  }

  const session = activeSession();
  if (!session) return;

  const now = Date.now();
  const userMsg = {
    id: crypto.randomUUID(),
    role: "user",
    content,
    toolStatus: null,
    createdAt: now,
  };
  const assistantMsg = {
    id: crypto.randomUUID(),
    role: "assistant",
    content: "",
    toolStatus: null,
    createdAt: now,
  };

  session.messages = [...session.messages, userMsg, assistantMsg];
  session.updatedAt = now;

  if (!session.titleEdited && session.messages.filter((m) => m.role === "user").length === 1) {
    session.title = autoTitle(content);
  }

  ui.sessions = [...ui.sessions];
  ui.streaming = true;
  flushSave();

  const appendDelta = (chunk) => {
    const s = activeSession();
    if (!s) return;
    const last = s.messages[s.messages.length - 1];
    if (!last || last.role !== "assistant") return;
    last.content += chunk;
    s.updatedAt = Date.now();
    ui.sessions = [...ui.sessions];
    scheduleSave();
  };

  const setToolStatus = (label) => {
    const s = activeSession();
    if (!s) return;
    const last = s.messages[s.messages.length - 1];
    if (!last || last.role !== "assistant") return;
    last.toolStatus = label;
    ui.sessions = [...ui.sessions];
    scheduleSave();
  };

  try {
    const response = await chat(session.id, content);
    if (!response.ok || !response.body) {
      appendDelta(`[error] HTTP ${response.status}`);
      return;
    }

    await parseSseStream(response.body, (ev) => {
      if (ev.type === "delta") {
        appendDelta(ev.content);
      } else if (ev.type === "tool_call") {
        setToolStatus(`🔧 ${ev.call.name} 호출 중...`);
      } else if (ev.type === "tool_result") {
        setToolStatus(`🔧 ${ev.name} → ${ev.result}`);
      } else if (ev.type === "error") {
        appendDelta(`\n\n[error] ${ev.message}`);
      }
    });
  } catch (e) {
    appendDelta(`\n\n[error] ${String(e)}`);
  } finally {
    ui.streaming = false;
    flushSave();
  }
}

// ---------- 초기화 ----------

export async function initApp() {
  ui.theme = loadTheme();
  document.documentElement.setAttribute("data-theme", ui.theme);

  const sessions = loadSessions();
  ui.sessions = sessions.sort((a, b) => b.updatedAt - a.updatedAt);

  const storedActive = loadActiveId();
  const activeId = sessions.some((s) => s.id === storedActive)
    ? storedActive
    : (sessions[0]?.id ?? null);

  ui.activeSessionId = activeId;

  if (activeId) {
    openPresence(activeId);
    const s = ui.sessions.find((x) => x.id === activeId);
    if (s && s.messages.length > 0) {
      await restoreConversation(activeId, toBackendMessages(s.messages));
    }
  }

  pollUpdate();
}

export function setTheme(theme) {
  ui.theme = theme;
  saveTheme(theme);
  document.documentElement.setAttribute("data-theme", theme);
}

export function toggleTheme() {
  setTheme(ui.theme === "light" ? "dark" : "light");
}

export function toggleSidebar() {
  ui.sidebarOpen = !ui.sidebarOpen;
}

// ---------- 업데이트 (기존 로직 보존, 액션 모듈로 이전) ----------

async function pollUpdate() {
  const data = await checkUpdate();
  if (!data) return;
  ui.updateInfo = data;

  const dismissedFor = sessionStorage.getItem("update_dismissed_for");
  if (dismissedFor && dismissedFor === data.latest) {
    ui.updateDismissed = true;
  }
}

export function dismissUpdate() {
  ui.updateDismissed = true;
  if (ui.updateInfo?.latest) {
    sessionStorage.setItem("update_dismissed_for", ui.updateInfo.latest);
  }
}

export async function startUpdate() {
  ui.applying = true;
  ui.applyState = { status: "starting", progress: 0, total: 0, message: "" };
  ui.modalOpen = true;

  const pollId = setInterval(async () => {
    const state = await getUpdateStatus().catch(() => null);
    if (state) {
      ui.applyState = state;
    } else {
      // 서버가 내려가는 중 — restart 단계로 전환.
      clearInterval(pollId);
      ui.restarting = true;
    }
  }, UPDATE_POLL_MS);

  try {
    const data = await applyUpdate();
    if (!data.ok) {
      clearInterval(pollId);
      ui.applying = false;
      ui.applyState = { status: "error", message: data.error || "unknown" };
    }
  } catch (e) {
    clearInterval(pollId);
    ui.applying = false;
    ui.applyState = { status: "error", message: String(e) };
  }
}

export function closeUpdateModal() {
  ui.modalOpen = false;
  ui.applying = false;
}

export function teardown() {
  closePresence();
  flushSave();
}
