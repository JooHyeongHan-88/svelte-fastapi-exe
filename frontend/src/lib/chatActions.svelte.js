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
  listSkills,
} from "./api.js";
import { parseSseStream } from "./sse.js";
import { autoTitle } from "./format.js";

const SAVE_DEBOUNCE_MS = 200;
const UPDATE_POLL_MS = 500;

// 탭이 열려 있는 동안 서버를 살려두기 위한 브라우저 레벨 presence ID.
// 세션 유무와 무관하게 탭이 닫힐 때까지 연결을 유지하므로 세션 삭제 시 서버가
// 종료되는 버그를 방지한다. 페이지 로드마다 새로 발급해도 grace 기간 안에
// 새 연결이 올라와 watchdog 은 계속 "alive" 로 판정한다.
const BROWSER_KEEPALIVE_ID = `bpid-${crypto.randomUUID()}`;

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

// ---------- presence ----------
// 규칙: presenceSource 는 항상 1개. 세션이 있으면 해당 세션 ID, 없으면
// BROWSER_KEEPALIVE_ID 로 열어 탭이 닫힐 때까지 서버를 살려 둔다.

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
      // 세션이 모두 사라졌지만 브라우저는 열려 있다 — keepalive 로 전환해 서버 종료를 막는다.
      // 다음 createSession() 이 호출되면 openPresence(sessionId) 가 이 연결을 교체한다.
      openPresence(BROWSER_KEEPALIVE_ID);
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
  const displayContent = text.trim();
  const hasSkills = ui.composerSkills.length > 0;

  // 텍스트가 없어도 skill chip 이 부착돼 있으면 전송을 허용한다.
  if ((!displayContent && !hasSkills) || ui.streaming) return;

  // 활성 세션이 없으면 즉석 생성 (첫 메시지 시나리오).
  if (!ui.activeSessionId) {
    await createSession();
  }

  // 직전 assistant 메시지에 미답변 askUser 가 있으면 answered 로 마킹한다.
  // 사용자가 옵션 버튼 또는 직접 입력으로 응답을 보내는 시점에 카드를 비활성화한다.
  {
    const cur = activeSession();
    if (cur) {
      for (let i = cur.messages.length - 1; i >= 0; i--) {
        const m = cur.messages[i];
        if (m.role === "user") break; // 직전 user 메시지를 만나면 중단
        if (m.role === "assistant" && m.askUser && !m.askUser.answered) {
          m.askUser = { ...m.askUser, answered: true };
          break;
        }
      }
    }
  }

  const session = activeSession();
  if (!session) return;

  const now = Date.now();

  // composerSkills 가 비어 있지 않다면 사용자가 슬래시로 명시한 것 — 응답이 오기 전에도
  // 즉시 뱃지가 보이도록 초기값으로 복사. skill_active 이벤트가 와도 동일 목록이므로 멱등.
  const forced = hasSkills ? [...ui.composerSkills] : null;

  const userMsg = {
    id: crypto.randomUUID(),
    role: "user",
    content: displayContent,          // UI 표시용 — 빈 문자열 가능 (skill 만 전송한 경우)
    appliedSkills: forced,            // 대화창 내 skill 뱃지 표시용
    toolStatus: null,
    createdAt: now,
  };
  const assistantMsg = {
    id: crypto.randomUUID(),
    role: "assistant",
    content: "",
    toolStatus: null,
    activeSkills: forced, // string[] | null — skill_active 이벤트로 채워진다
    reasoning: "",        // ReasoningEvent 청크가 누적되는 추론 텍스트
    todos: null,          // TodoUpdateEvent 로 갱신되는 TodoItem[] | null
    skillComplete: null,  // SkillCompleteEvent 로 설정되는 {completed, failed, skipped} | null
    askUser: null,        // AskUserEvent 로 설정되는 슬롯 질문 | null
    agentTrail: [],       // {from, to, reason, summary, todoLog, toolCallsCount, errorCount}
    agentProgress: [],    // {agentId, deltas, toolStatus, todos, skillComplete}
    createdAt: now,
  };

  session.messages = [...session.messages, userMsg, assistantMsg];
  session.updatedAt = now;

  if (!session.titleEdited && session.messages.filter((m) => m.role === "user").length === 1) {
    // 본문 없이 skill 만 전송한 경우 skill 이름으로 제목을 채운다.
    session.title = autoTitle(displayContent || (forced ? forced.join(", ") : "새 대화"));
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

  const setActiveSkills = (skills) => {
    const s = activeSession();
    if (!s) return;
    const last = s.messages[s.messages.length - 1];
    if (!last || last.role !== "assistant") return;
    last.activeSkills = skills;
    ui.sessions = [...ui.sessions];
    // 스킬 목록은 내용이 아니므로 저장은 생략 (메모리에만 유지)
  };

  const appendReasoning = (chunk) => {
    const s = activeSession();
    if (!s) return;
    const last = s.messages[s.messages.length - 1];
    if (!last || last.role !== "assistant") return;
    last.reasoning = (last.reasoning ?? "") + chunk;
    s.updatedAt = Date.now();
    ui.sessions = [...ui.sessions];
    scheduleSave();
  };

  const setTodos = (todos) => {
    const s = activeSession();
    if (!s) return;
    const last = s.messages[s.messages.length - 1];
    if (!last || last.role !== "assistant") return;
    last.todos = todos;
    ui.sessions = [...ui.sessions];
    scheduleSave();
  };

  const setSkillComplete = (data) => {
    const s = activeSession();
    if (!s) return;
    const last = s.messages[s.messages.length - 1];
    if (!last || last.role !== "assistant") return;
    last.skillComplete = data;
    ui.sessions = [...ui.sessions];
    scheduleSave();
  };

  const setAskUser = (payload) => {
    const s = activeSession();
    if (!s) return;
    const last = s.messages[s.messages.length - 1];
    if (!last || last.role !== "assistant") return;
    last.askUser = payload;
    ui.sessions = [...ui.sessions];
    scheduleSave();
  };

  // ── 멀티 에이전트 이벤트 핸들러 ─────────────────────────────────────
  // AgentSwitchEvent → trail 에 새 항목 push (요약 비어 있음)
  const pushAgentSwitch = (from, to, reason) => {
    const s = activeSession();
    if (!s) return;
    const last = s.messages[s.messages.length - 1];
    if (!last || last.role !== "assistant") return;
    last.agentTrail = [
      ...(last.agentTrail ?? []),
      { from, to, reason, summary: null },
    ];
    // 새 progress 슬롯도 미리 열어 둔다 (delta 누적용).
    last.agentProgress = [
      ...(last.agentProgress ?? []),
      {
        agentId: to,
        deltas: "",
        toolStatus: null,
        todos: null,
        skillComplete: null,
        activeSkills: null, // sub-agent SKILL 뱃지 (AgentProgressEvent[skill_active])
        reasoning: "",      // sub-agent 의 ReasoningEvent 청크 누적 — 별도 토글 블록으로 렌더
      },
    ];
    ui.sessions = [...ui.sessions];
    scheduleSave();
  };

  // AgentReturnEvent → trail 의 마지막 항목 summary + todo_log 채움.
  // todo_log 가 있으면 progress 슬롯 todos 도 동기화 (todo_update 미수신 시 fallback).
  const pushAgentReturn = (from, summary, todoLog, toolCallsCount, errorCount) => {
    const s = activeSession();
    if (!s) return;
    const last = s.messages[s.messages.length - 1];
    if (!last || last.role !== "assistant") return;

    const trail = [...(last.agentTrail ?? [])];
    for (let i = trail.length - 1; i >= 0; i--) {
      if (trail[i].to === from && trail[i].summary == null) {
        trail[i] = { ...trail[i], summary, todoLog: todoLog ?? [], toolCallsCount: toolCallsCount ?? 0, errorCount: errorCount ?? 0 };
        break;
      }
    }
    last.agentTrail = trail;

    // progress 슬롯 todos fallback — todo_update 없이 완료된 경우 보완.
    if (todoLog && todoLog.length > 0) {
      const progress = [...(last.agentProgress ?? [])];
      for (let i = progress.length - 1; i >= 0; i--) {
        if (progress[i].agentId === from) {
          if (!progress[i].todos || progress[i].todos.length === 0) {
            progress[i] = { ...progress[i], todos: todoLog };
            last.agentProgress = progress;
          }
          break;
        }
      }
    }

    ui.sessions = [...ui.sessions];
    scheduleSave();
  };

  // AgentProgressEvent → 현재 활성 progress 슬롯에 inner 이벤트 반영
  const handleAgentProgress = (agentId, innerType, innerPayload) => {
    const s = activeSession();
    if (!s) return;
    const last = s.messages[s.messages.length - 1];
    if (!last || last.role !== "assistant") return;
    const progress = [...(last.agentProgress ?? [])];
    // 같은 agentId 의 마지막 슬롯을 찾는다 (없으면 새로 추가).
    let slotIdx = -1;
    for (let i = progress.length - 1; i >= 0; i--) {
      if (progress[i].agentId === agentId) {
        slotIdx = i;
        break;
      }
    }
    if (slotIdx === -1) {
      progress.push({
        agentId,
        deltas: "",
        toolStatus: null,
        todos: null,
        skillComplete: null,
        activeSkills: null,
        reasoning: "",
      });
      slotIdx = progress.length - 1;
    }
    const slot = { ...progress[slotIdx] };
    if (innerType === "delta") {
      slot.deltas += innerPayload.content ?? "";
    } else if (innerType === "tool_call") {
      slot.toolStatus = `🔧 ${innerPayload.call?.name ?? "?"} 호출 중...`;
    } else if (innerType === "tool_result") {
      const prefix = innerPayload.is_error ? "⚠️" : "🔧";
      slot.toolStatus = `${prefix} ${innerPayload.name ?? "?"} → ${innerPayload.result ?? ""}`;
    } else if (innerType === "reasoning") {
      // sub-agent 의 추론도 메인과 동일하게 ReasoningBlock 토글로 표시 — 별도 필드에 누적.
      slot.reasoning = (slot.reasoning ?? "") + (innerPayload.content ?? "");
    } else if (innerType === "todo_update") {
      slot.todos = innerPayload.todos ?? [];
    } else if (innerType === "skill_active") {
      slot.activeSkills = innerPayload.skills ?? [];
    } else if (innerType === "skill_complete") {
      slot.skillComplete = {
        completed: innerPayload.completed ?? 0,
        failed: innerPayload.failed ?? 0,
        skipped: innerPayload.skipped ?? 0,
      };
    }
    progress[slotIdx] = slot;
    last.agentProgress = progress;
    ui.sessions = [...ui.sessions];
    scheduleSave();
  };

  // 백엔드로 보낼 force_skills 를 미리 캡처 후, 다음 입력에 잔여물이 남지 않도록 즉시 리셋.
  const forceSkills = forced;
  ui.composerSkills = [];

  // LLM 에 전달할 실제 메시지 — 본문이 비어 있으면 skill 이름으로 대체해 의미 있는 컨텍스트 제공.
  const llmContent = displayContent || (forceSkills ? forceSkills.join(", ") : "");

  try {
    const response = await chat(session.id, llmContent, { forceSkills });
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
        // is_error 면 시각적으로 구분. data 필드는 향후 inspector UI 에서 활용 예정.
        const prefix = ev.is_error ? "⚠️" : "🔧";
        setToolStatus(`${prefix} ${ev.name} → ${ev.result}`);
      } else if (ev.type === "skill_active") {
        setActiveSkills(ev.skills);
      } else if (ev.type === "error") {
        appendDelta(`\n\n[error] ${ev.message}`);
      } else if (ev.type === "reasoning") {
        appendReasoning(ev.content);
      } else if (ev.type === "todo_update") {
        setTodos(ev.todos);
      } else if (ev.type === "skill_complete") {
        setSkillComplete({ completed: ev.completed, failed: ev.failed, skipped: ev.skipped });
      } else if (ev.type === "ask_user") {
        setAskUser({
          question: ev.question,
          slot_key: ev.slot_key,
          options: ev.options ?? null,
          tool_name: ev.tool_name ?? null,
          // 백엔드가 명시한 input_type 을 신뢰하되, 누락 시 options 유무로 폴백.
          input_type: ev.input_type ?? (ev.options ? "both" : "text"),
          answered: false,
        });
      } else if (ev.type === "agent:switch") {
        pushAgentSwitch(ev.from_agent, ev.to_agent, ev.reason ?? "");
      } else if (ev.type === "agent:return") {
        pushAgentReturn(ev.from_agent, ev.summary ?? "", ev.todo_log ?? [], ev.tool_calls_count ?? 0, ev.error_count ?? 0);
      } else if (ev.type === "agent:progress") {
        handleAgentProgress(ev.agent_id, ev.inner_type, ev.inner_payload ?? {});
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
  } else {
    // 저장된 세션이 없어도 탭이 열려 있는 동안 서버를 유지한다.
    openPresence(BROWSER_KEEPALIVE_ID);
  }

  // 슬래시 커맨드 autocomplete 데이터 — 부팅 시 1회. 실패해도 입력은 정상 작동.
  listSkills().then((skills) => {
    ui.availableSkills = skills;
  });

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
