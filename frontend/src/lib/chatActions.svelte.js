// 세션/메시지 액션. UI 는 이 함수들만 호출하고, localStorage 와 백엔드 sync 는 여기서 책임진다.

import { ui, activeSession } from "./state.svelte.js";
import {
  loadSessions,
  saveSessions,
  loadActiveId,
  saveActiveId,
  loadTheme,
  saveTheme,
  loadArtifactWidth,
  loadArtifactPanelOpen,
  loadSidebarWidth,
} from "./storage.js";
import {
  chat,
  deleteConversation,
  deleteArtifactsForSession,
  getArtifactUsage,
  restoreConversation,
  checkUpdate,
  applyUpdate,
  getUpdateStatus,
  listSkills,
} from "./api.js";
import { getAppInfo } from "./settingsApi.js";
import { parseSseStream } from "./sse.js";
import { autoTitle } from "./format.js";

// ── 스트림 클럭 ──────────────────────────────────────────────────────────────
// 생성 중에만 1초 간격으로 ui.nowTick 을 갱신해 TurnStatus 의 경과 시간을 reactive 하게 만든다.
let _streamClockTimer = null;

function startStreamClock() {
  ui.nowTick = Date.now();
  _streamClockTimer = setInterval(() => {
    ui.nowTick = Date.now();
  }, 1000);
}

function stopStreamClock() {
  if (_streamClockTimer) {
    clearInterval(_streamClockTimer);
    _streamClockTimer = null;
  }
}
import {
  makeArtifactChip,
  resetArtifactPanelState,
} from "./artifactActions.svelte.js";

const SAVE_DEBOUNCE_MS = 200;
const UPDATE_POLL_MS = 500;

// 탭이 열려 있는 동안 서버를 살려두기 위한 브라우저 레벨 presence ID.
// 세션 유무와 무관하게 탭이 닫힐 때까지 연결을 유지하므로 세션 삭제 시 서버가
// 종료되는 버그를 방지한다.
const BROWSER_KEEPALIVE_ID = `bpid-${crypto.randomUUID()}`;

let presenceSource = null;
let saveTimer = null;
// 진행 중인 /api/chat 요청을 ESC 로 중지하기 위한 핸들.
let currentAbortController = null;

// ---------- 영속화 ----------

// 저장 전 tool 세그먼트의 bulky data 필드를 제거한다.
// 아티팩트는 디스크 + artifactChips 에 이미 보존되므로 data 없이도 복원 가능.
function _cleanSegmentsForStorage(segs) {
  if (!segs || segs.length === 0) return segs;
  return segs.map((seg) => {
    if (seg.kind === "tool") return { ...seg, data: null };
    if (seg.kind === "subagent") return { ...seg, segments: _cleanSegmentsForStorage(seg.segments) };
    return seg;
  });
}

function _cleanSessionsForStorage(sessions) {
  return sessions.map((session) => ({
    ...session,
    messages: session.messages.map((msg) => {
      if (!msg.segments || msg.segments.length === 0) return msg;
      return { ...msg, segments: _cleanSegmentsForStorage(msg.segments) };
    }),
  }));
}

function scheduleSave() {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    saveSessions(_cleanSessionsForStorage(ui.sessions));
    saveTimer = null;
  }, SAVE_DEBOUNCE_MS);
}

function flushSave() {
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
  saveSessions(_cleanSessionsForStorage(ui.sessions));
}

// ---------- presence ----------
// 규칙: presenceSource 는 항상 1개. 세션이 있으면 해당 세션 ID, 없으면
// BROWSER_KEEPALIVE_ID 로 열어 탭이 닫힐 때까지 서버를 살려 둔다.

function openPresence(clientId) {
  closePresence();
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

// parts(텍스트+인용 pill 의 순서 있는 배열) → LLM 와이어 본문. 각 pill 자리에 실제
// result/... 경로를 인라인으로 박아 LLM 이 "이 파일의 그 컬럼" 같은 위치 의존 지시를
// 그대로 이해하게 한다. text 는 값 그대로, ref 는 path 로 치환해 이어붙인다.
function _wireFromParts(parts) {
  return (parts ?? [])
    .map((p) => (p.type === "ref" ? p.path : (p.value ?? "")))
    .join("");
}

// parts → 사람이 읽는 표시 문자열 (ref 는 파일명 라벨). 제목 생성·레거시 폴백용.
function _displayFromParts(parts) {
  return (parts ?? [])
    .map((p) => (p.type === "ref" ? p.label : (p.value ?? "")))
    .join("");
}

// parts 정규화 — 인접 text 병합·빈 text 제거·ref 형태 보존. pill 주위 공백은 의미가 있어 유지한다.
function _normalizeParts(parts) {
  const out = [];
  for (const p of parts ?? []) {
    if (!p) continue;
    if (p.type === "ref" && p.path) {
      out.push({ type: "ref", path: p.path, label: p.label || p.path });
    } else if (p.type === "text" && p.value) {
      const last = out[out.length - 1];
      if (last && last.type === "text") last.value += p.value;
      else out.push({ type: "text", value: p.value });
    }
  }
  return out;
}

// (구) refs 모델 폴백 — 직전 구현으로 localStorage 에 남은 메시지 호환. content 뒤에 경로를 잇는다.
function _mergeRefPaths(content, refs) {
  const paths = (refs ?? []).map((r) => r?.path).filter(Boolean);
  if (paths.length === 0) return content ?? "";
  return [content, ...paths].filter(Boolean).join("\n");
}

// 메시지 1건의 백엔드 전송 본문. parts(신규) 우선, refs(구) 차선, 그 외 content 평문.
function _backendContent(m) {
  if (Array.isArray(m.parts) && m.parts.length > 0) return _wireFromParts(m.parts);
  if (m.refs && m.refs.length > 0) return _mergeRefPaths(m.content, m.refs);
  return m.content ?? "";
}

function toBackendMessages(uiMessages) {
  // UI 모델 → backend Message 스키마. segments/id/createdAt 은 백엔드에 보내지 않음.
  // user 메시지의 인용은 _backendContent 가 경로로 합성해 LLM context 에 포함시킨다.
  return uiMessages.map((m) => ({ role: m.role, content: _backendContent(m) }));
}

export async function createSession() {
  if (ui.streaming) return;

  const session = newSession();
  ui.sessions = [session, ...ui.sessions];
  ui.activeSessionId = session.id;
  saveActiveId(session.id);
  flushSave();
  resetArtifactPanelState();

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
  resetArtifactPanelState();

  openPresence(id);
  // EXE 재시작 등으로 백엔드 context 가 비어있을 수 있으므로 매 선택마다 다시 주입.
  await restoreConversation(id, toBackendMessages(target.messages));
}

export async function deleteSession(id) {
  if (ui.streaming) return;

  const idx = ui.sessions.findIndex((s) => s.id === id);
  if (idx === -1) return;

  ui.sessions = ui.sessions.filter((s) => s.id !== id);
  // 대화 히스토리와 함께 그 세션에서 생성된 산출물 폴더도 정리한다 (디스크 누적 방지).
  await deleteConversation(id);
  await deleteArtifactsForSession(id);

  if (ui.activeSessionId === id) {
    const next = ui.sessions[0] ?? null;
    ui.activeSessionId = next?.id ?? null;
    saveActiveId(ui.activeSessionId);

    if (next) {
      openPresence(next.id);
      await restoreConversation(next.id, toBackendMessages(next.messages));
    } else {
      // 세션이 모두 사라졌지만 브라우저는 열려 있다 — keepalive 로 전환해 서버 종료를 막는다.
      openPresence(BROWSER_KEEPALIVE_ID);
    }
  }

  flushSave();
  refreshArtifactUsage();
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

export async function sendMessage(input) {
  // 입력은 parts 배열(텍스트+인용 pill 순서 보존). 하위호환으로 문자열도 받아 단일 text part 로 감싼다.
  const parts = Array.isArray(input)
    ? _normalizeParts(input)
    : _normalizeParts([{ type: "text", value: String(input ?? "") }]);

  const displayContent = _displayFromParts(parts).trim();
  const hasSkills = ui.composerSkills.length > 0;
  const hasRefs = parts.some((p) => p.type === "ref");

  // 텍스트가 없어도 skill chip 이나 산출물 인용이 부착돼 있으면 전송을 허용한다.
  if ((!displayContent && !hasSkills && !hasRefs) || ui.streaming) return;

  // 활성 세션이 없으면 즉석 생성 (첫 메시지 시나리오).
  if (!ui.activeSessionId) {
    await createSession();
  }

  // 직전 assistant 메시지에 미답변 askUser 가 있으면 answered 로 마킹한다.
  {
    const cur = activeSession();
    if (cur) {
      for (let i = cur.messages.length - 1; i >= 0; i--) {
        const m = cur.messages[i];
        if (m.role === "user") break;
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
  const forced = hasSkills ? [...ui.composerSkills] : null;
  const firstRefLabel = parts.find((p) => p.type === "ref")?.label ?? "";

  const userMsg = {
    id: crypto.randomUUID(),
    role: "user",
    // content 는 라벨 인라인 표시 문자열(제목·레거시 폴백용). 백엔드 본문은 parts→경로로 따로 합성.
    content: displayContent,
    parts, // 인용 pill 의 위치를 보존하는 구조 필드 (버블 인라인 렌더·복원용)
    appliedSkills: forced,
    toolStatus: null,
    createdAt: now,
  };

  const assistantMsg = {
    id: crypto.randomUUID(),
    role: "assistant",
    content: "",          // 백엔드 restore 용 — delta 수신 시 함께 누적
    segments: [],         // 시간순 Collapsible 타임라인 (Segment[] 배열)
    activeSkills: forced, // 상단 skill 칩 (message 레벨, skill_active 이벤트로 갱신)
    askUser: null,        // AskUserEvent 로 설정되는 슬롯 질문 | null
    artifactChips: [],
    isStopped: false,
    isFallback: false,
    createdAt: now,
    // ── 진행 상태 타이밍 필드 ──
    streaming: true,      // 이 메시지가 현재 생성 중인지 (per-message 플래그)
    startedAt: now,       // 생성 시작 시각 (ms)
    finishedAt: null,     // 생성 종료 시각 (ms)
    durationMs: null,     // finishedAt - startedAt (완료 후 확정)
  };

  session.messages = [...session.messages, userMsg, assistantMsg];
  session.updatedAt = now;

  if (!session.titleEdited && session.messages.filter((m) => m.role === "user").length === 1) {
    const titleSeed =
      displayContent || (forced ? forced.join(", ") : "") || firstRefLabel || "새 대화";
    session.title = autoTitle(titleSeed);
  }

  ui.sessions = [...ui.sessions];
  ui.streaming = true;
  startStreamClock();
  flushSave();

  // 백엔드로 보낼 force_skills 를 미리 캡처 후, 다음 입력에 잔여물이 남지 않도록 즉시 리셋.
  const forceSkills = forced;
  ui.composerSkills = [];

  // LLM 에 전달할 실제 메시지 — parts 의 pill 자리에 경로를 인라인 합성한다
  // (toBackendMessages 복원과 동일 와이어 본문). 본문이 비면 skill 이름으로 대체.
  const llmContent = _wireFromParts(parts) || (forceSkills ? forceSkills.join(", ") : "");

  currentAbortController = new AbortController();
  const abortSignal = currentAbortController.signal;

  try {
    const response = await chat(session.id, llmContent, {
      forceSkills,
      sessionTitle: session.title,
      signal: abortSignal,
    });
    if (!response.ok || !response.body) {
      const s = activeSession();
      const msg = s?.messages.at(-1);
      if (msg?.role === "assistant") {
        const errText = `[error] HTTP ${response.status}`;
        msg.content += errText;
        _applyEvent(msg.segments, { type: "delta", content: errText }, null, null);
        ui.sessions = [...ui.sessions];
        scheduleSave();
      }
      return;
    }

    await parseSseStream(
      response.body,
      (ev) => {
        const s = activeSession();
        if (!s) return;
        const msg = s.messages.at(-1);
        if (!msg || msg.role !== "assistant") return;

        // 아티팩트 칩 추가 콜백 — 항상 message 레벨 (서브에이전트 내부 도구도 동일).
        // open: 시각화 칩은 패널 자동 오픈, 데이터 칩은 칩만 추가 (중간 저장마다
        // 패널이 튀지 않도록).
        const addChip = (kind, payload, { open = true } = {}) => {
          const chip = makeArtifactChip(kind, payload);
          msg.artifactChips = [...(msg.artifactChips ?? []), chip];
          if (open) {
            ui.activeArtifactId = chip.id;
            ui.artifactPanelOpen = true;
          }
        };

        // 최상위 scope 의 activeSkills 세터
        const setTopSkills = (skills) => {
          msg.activeSkills = skills;
        };

        if (ev.type === "delta") {
          // content 는 restore 용으로 계속 누적한다.
          msg.content += ev.content ?? "";
          s.updatedAt = Date.now();
          _applyEvent(msg.segments, ev, addChip, setTopSkills);
          ui.sessions = [...ui.sessions];
          scheduleSave();
        } else if (
          ev.type === "reasoning" ||
          ev.type === "tool_call" ||
          ev.type === "tool_result" ||
          ev.type === "todo_update" ||
          ev.type === "skill_complete"
        ) {
          _applyEvent(msg.segments, ev, addChip, setTopSkills);
          ui.sessions = [...ui.sessions];
          scheduleSave();
        } else if (ev.type === "skill_active") {
          // message 레벨 칩 갱신 (segments 바깥 상단에 표시)
          msg.activeSkills = ev.skills ?? [];
          ui.sessions = [...ui.sessions];
        } else if (ev.type === "error") {
          if (ev.is_fallback) {
            // is_recovered: 반복 예산 소진이지만 모든 todo 완료 → 중립(완료) 스타일
            // !is_recovered: 작업 미완 → 경고(danger) 스타일
            msg.isFallback = !ev.is_recovered;
            for (let i = msg.segments.length - 1; i >= 0; i--) {
              if (msg.segments[i].kind === "text") {
                msg.segments[i].isFallback = !ev.is_recovered;
                msg.segments[i].isRecovered = !!ev.is_recovered;
                break;
              }
            }
          } else {
            const errContent = `\n\n[error] ${ev.message}`;
            msg.content += errContent;
            _applyEvent(msg.segments, { type: "delta", content: errContent }, null, null);
          }
          ui.sessions = [...ui.sessions];
          scheduleSave();
        } else if (ev.type === "ask_user") {
          msg.askUser = {
            question: ev.question,
            slot_key: ev.slot_key,
            options: ev.options ?? null,
            tool_name: ev.tool_name ?? null,
            // 백엔드가 명시한 input_type 을 신뢰하되, 누락 시 options 유무로 폴백.
            input_type: ev.input_type ?? (ev.options ? "both" : "text"),
            answered: false,
          };
          ui.sessions = [...ui.sessions];
          scheduleSave();
        } else if (ev.type === "agent:switch") {
          // 서브에이전트 세그먼트를 push — 내부 segments 는 agent:progress 가 채운다.
          // dispatchId: 병렬 실행 시 같은 이름 에이전트가 둘 이상 동시에 떠도 이벤트를
          // 정확한 트레일로 라우팅하는 상관키 (백엔드가 디스패치별로 부여).
          msg.segments.push({
            kind: "subagent",
            id: _segId(),
            agentId: ev.to_agent,
            dispatchId: ev.dispatch_id ?? null,
            reason: ev.reason ?? "",
            status: "running",
            summary: null,
            segments: [],
            activeSkills: null,
          });
          ui.sessions = [...ui.sessions];
          scheduleSave();
        } else if (ev.type === "agent:progress") {
          // dispatchId 우선 → 없으면 agentId 기반 마지막 running 세그먼트에 재귀 적용.
          const sub = _findSubagentForEvent(msg.segments, ev);
          if (sub) {
            const inner = { type: ev.inner_type, ...(ev.inner_payload ?? {}) };
            _applyEvent(
              sub.segments,
              inner,
              addChip,                             // 칩은 message 레벨
              (skills) => { sub.activeSkills = skills; }, // 스킬은 subagent 레벨
            );
          }
          ui.sessions = [...ui.sessions];
          scheduleSave();
        } else if (ev.type === "agent:return") {
          // 서브에이전트 세그먼트를 done 으로 확정 (dispatchId 우선 라우팅).
          const sub = _findSubagentForEvent(msg.segments, ev);
          if (sub) {
            sub.status = "done";
            sub.summary = ev.summary ?? null;
            // todo_update 없이 완료된 경우 todo_log 로 폴백 (내부 todo 세그먼트 추가).
            const hasTodo = sub.segments.some((sg) => sg.kind === "todo");
            if (!hasTodo && ev.todo_log && ev.todo_log.length > 0) {
              sub.segments.push({
                kind: "todo",
                id: _segId(),
                todos: ev.todo_log,
                complete: null,
              });
            }
          }
          ui.sessions = [...ui.sessions];
          scheduleSave();
        }
      },
      abortSignal,
    );
  } catch (e) {
    // AbortError 는 stopStreaming() 이 유도한 정상 흐름이므로 에러 텍스트를 추가하지 않는다.
    if (e?.name !== "AbortError" && !abortSignal.aborted) {
      const s = activeSession();
      const msg = s?.messages.at(-1);
      if (msg?.role === "assistant") {
        const errContent = `\n\n[error] ${String(e)}`;
        msg.content += errContent;
        _applyEvent(msg.segments, { type: "delta", content: errContent }, null, null);
        ui.sessions = [...ui.sessions];
      }
    }
  } finally {
    // 타이밍 확정 — 정상 완료·에러·ESC 중단 모두 동일 경로.
    // assistantMsg 는 plain object 이므로 Svelte 5 reactive proxy 를 통해 수정해야
    // 반응성이 트리거된다. stopStreaming() 과 동일하게 세션에서 직접 조회한다.
    const finishedAt = Date.now();
    const s = activeSession();
    const msg = s?.messages.at(-1);
    if (msg?.role === "assistant") {
      msg.streaming = false;
      msg.finishedAt = finishedAt;
      msg.durationMs = finishedAt - (msg.startedAt ?? finishedAt);
    }
    ui.streaming = false;
    stopStreamClock();
    currentAbortController = null;
    ui.sessions = [...ui.sessions];
    flushSave();
    // 이번 턴에 산출물이 생겼을 수 있으므로 사이드바 용량을 갱신한다.
    refreshArtifactUsage();
  }
}

// 특정 user 메시지 시점으로 대화를 되돌린다.
export async function rewindToMessage(messageId) {
  if (ui.streaming) return;
  const session = activeSession();
  if (!session) return;

  const index = session.messages.findIndex((m) => m.id === messageId);
  if (index < 0) return;

  const target = session.messages[index];
  if (target.role !== "user") return;

  // 인용 pill 위치까지 그대로 되살린다. parts 가 없으면(레거시·refs) 평문으로 복원.
  const capturedParts =
    Array.isArray(target.parts) && target.parts.length > 0
      ? target.parts.map((p) =>
          p.type === "ref"
            ? { type: "ref", path: p.path, label: p.label }
            : { type: "text", value: p.value ?? "" },
        )
      : [{ type: "text", value: target.content ?? "" }];

  session.messages = session.messages.slice(0, index);
  session.updatedAt = Date.now();
  ui.sessions = [...ui.sessions];
  flushSave();

  resetArtifactPanelState();

  await restoreConversation(session.id, toBackendMessages(session.messages));

  ui.composerSetParts = { parts: capturedParts, nonce: Date.now() + Math.random() };
}

// 진행 중인 응답 스트리밍을 중지한다. ESC 키 핸들러가 호출한다.
export function stopStreaming() {
  if (!ui.streaming || !currentAbortController) return;
  currentAbortController.abort();

  const s = activeSession();
  if (!s) return;
  const last = s.messages.at(-1);
  if (last?.role === "assistant") {
    last.isStopped = true;
    ui.sessions = [...ui.sessions];
    flushSave();
  }
}

// ---------- 산출물 용량 ----------

// 세션별 산출물 총 용량 맵을 백엔드에서 가져와 사이드바 표시값을 갱신한다.
// 초기화·턴 종료·세션 삭제 시점에 호출 (best-effort — 실패 시 기존 값 유지).
export async function refreshArtifactUsage() {
  const usage = await getArtifactUsage();
  ui.artifactUsage = usage;
}

// ---------- 초기화 ----------

export async function initApp() {
  ui.theme = loadTheme();
  document.documentElement.setAttribute("data-theme", ui.theme);
  ui.artifactWidth = loadArtifactWidth();
  ui.artifactPanelOpen = loadArtifactPanelOpen();
  ui.sidebarWidth = loadSidebarWidth();

  const sessions = loadSessions();
  // 앱이 생성 도중 강제 종료되면 localStorage 에 streaming:true 가 잔류할 수 있다.
  // 재기동 시 모든 메시지의 streaming 플래그를 false 로 강제 확정한다.
  for (const s of sessions) {
    for (const m of s.messages ?? []) {
      if (m.streaming) {
        m.streaming = false;
        // finishedAt/durationMs 가 없으면 hover 소요시간은 생략된다 (그대로 둠).
      }
    }
  }
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
    openPresence(BROWSER_KEEPALIVE_ID);
  }

  listSkills().then((skills) => {
    ui.availableSkills = skills;
  });

  refreshArtifactUsage();

  getAppInfo()
    .then(({ name, version }) => {
      ui.appName = name;
      ui.appVersion = version ?? "";
      document.title = name;
    })
    .catch(() => {});

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

// ---------- 업데이트 ----------

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

  closePresence();

  const pollId = setInterval(async () => {
    const state = await getUpdateStatus().catch(() => null);
    if (state) {
      ui.applyState = state;
    } else {
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

// ---------- 내부 헬퍼 ----------

// 시각화 도구 결과인지 판별. tool_result / agent:progress 양쪽에서 공유한다.
const _ARTIFACT_TOOL_NAMES = new Set([
  "display_image",
  "display_chart",
  "display_markdown",
]);
const _ARTIFACT_KINDS = new Set(["image", "chart", "markdown"]);

// harness 가 모든 tool_call 을 프론트로 yield 하지만, sentinel 도구는 전용 세그먼트
// (subagent / todo / askUser / skill 칩) 로 따로 렌더되므로 도구 카드로 중복 표시하면 안 된다.
const _SENTINEL_TOOL_NAMES = new Set([
  "add_todo",
  "complete_todo",
  "call_sub_agent",
  "call_sub_agents_parallel",
  "activate_skill",
  "complete_subagent",
  "ask_user",
]);

function _isArtifactToolResult(ev) {
  return (
    !ev.is_error &&
    ev.data?.kind &&
    _ARTIFACT_KINDS.has(ev.data.kind) &&
    _ARTIFACT_TOOL_NAMES.has(ev.name)
  );
}

/**
 * parquet 중간 산출물 → 데이터 칩 payload 목록.
 * save_artifact 직접 저장과 exec_code 의 artifact_dir() 직접 쓰기(new_artifacts)
 * 양쪽을 커버한다. parquet 만 칩이 된다 (중간 데이터 영속 포맷 통일 방향).
 *
 * @param {{name?: string, is_error?: boolean, data?: object}} ev tool_result 이벤트
 * @returns {Array<{path: string, filename?: string, size?: number, rows?: number, columns?: number}>}
 */
function _dataArtifactPayloads(ev) {
  if (ev.is_error || !ev.data) return [];
  if (
    ev.name === "save_artifact" &&
    ev.data.kind === "parquet" &&
    typeof ev.data.path === "string"
  ) {
    const { path, filename, size, rows, columns } = ev.data;
    return [{ path, filename, size, rows, columns }];
  }
  if (ev.name === "exec_code" && Array.isArray(ev.data.new_artifacts)) {
    return ev.data.new_artifacts
      .filter((a) => a && a.kind === "parquet" && typeof a.path === "string")
      .map(({ path, filename, size }) => ({ path, filename, size }));
  }
  return [];
}

// ---------- segments 헬퍼 ----------

/** 짧은 고유 ID 생성 (세그먼트 key 용). */
function _segId() {
  return crypto.randomUUID().slice(0, 8);
}

/**
 * segments 배열에서 agentId 와 일치하는 마지막 running 서브에이전트 세그먼트를 반환한다.
 * agent:progress / agent:return 이벤트 라우팅에 사용한다.
 *
 * Args:
 *   segments: 검색할 세그먼트 배열
 *   agentId: 찾을 서브에이전트 ID
 *
 * Returns:
 *   일치하는 세그먼트 객체 또는 null
 */
function _findLastRunningSubagent(segments, agentId) {
  for (let i = segments.length - 1; i >= 0; i--) {
    const seg = segments[i];
    if (seg.kind === "subagent" && seg.agentId === agentId && seg.status === "running") {
      return seg;
    }
  }
  return null;
}

/**
 * agent:progress / agent:return 이벤트를 올바른 서브에이전트 세그먼트로 라우팅한다.
 *
 * dispatch_id 가 있으면(병렬 실행) 그 상관키로 정확히 매칭한다 — 같은 이름 에이전트가
 * 둘 이상 동시에 떠도 충돌하지 않는다. dispatch_id 가 없으면(구 세션·순차 폴백)
 * agentId 기반 '마지막 running' 휴리스틱으로 되돌아간다.
 *
 * Args:
 *   segments: 검색할 세그먼트 배열
 *   ev: agent:progress(agent_id) 또는 agent:return(from_agent) 이벤트
 *
 * Returns:
 *   일치하는 subagent 세그먼트 객체 또는 null
 */
function _findSubagentForEvent(segments, ev) {
  const agentId = ev.agent_id ?? ev.from_agent;
  if (ev.dispatch_id) {
    for (let i = segments.length - 1; i >= 0; i--) {
      const seg = segments[i];
      if (seg.kind === "subagent" && seg.dispatchId === ev.dispatch_id) {
        return seg;
      }
    }
    // dispatch_id 가 왔는데 매칭 세그먼트가 없으면(이론상 드묾) 이름 기반 폴백.
  }
  return _findLastRunningSubagent(segments, agentId);
}

/**
 * SSE 이벤트를 segments 배열에 시간순으로 누적한다.
 * 오케스트레이터와 서브에이전트가 동일 헬퍼를 재귀적으로 공유한다 — 재귀의 핵심.
 *
 * agent:switch / agent:progress / agent:return 은 최상위에서만 발생하므로
 * 이 함수에서는 처리하지 않는다.
 *
 * Args:
 *   segments: 누적 대상 배열 (in-place 변경)
 *   ev: 이벤트 객체 — { type, ...payload }
 *   addArtifactChip: 아티팩트 칩 추가 콜백 (kind, payload, {open}) => void | null
 *   setActiveSkills: 해당 scope 의 activeSkills 갱신 (skills[]) => void | null
 */
function _applyEvent(segments, ev, addArtifactChip, setActiveSkills) {
  switch (ev.type) {
    case "delta": {
      // 마지막 text 세그먼트에 이어붙이거나 새로 push (도구 호출로 끊기면 복수 text 가능)
      const last = segments.at(-1);
      if (last?.kind === "text") {
        last.content += ev.content ?? "";
      } else {
        segments.push({ kind: "text", id: _segId(), content: ev.content ?? "" });
      }
      break;
    }
    case "reasoning": {
      const last = segments.at(-1);
      if (last?.kind === "reasoning") {
        last.content += ev.content ?? "";
      } else {
        segments.push({ kind: "reasoning", id: _segId(), content: ev.content ?? "" });
      }
      break;
    }
    case "tool_call": {
      // sentinel 도구는 전용 세그먼트로 렌더되므로 도구 카드를 push 하지 않는다.
      // (대응 tool_result 도 매칭 세그먼트가 없어 자연히 no-op 처리된다.)
      if (_SENTINEL_TOOL_NAMES.has(ev.call?.name)) break;
      segments.push({
        kind: "tool",
        id: _segId(),
        callId: ev.call?.id ?? _segId(),
        name: ev.call?.name ?? "?",
        status: "running",
        detail: null,
        data: null,
      });
      break;
    }
    case "tool_result": {
      // tool_call_id 로 대응하는 tool 세그먼트를 찾아 확정한다.
      for (let i = segments.length - 1; i >= 0; i--) {
        if (segments[i].kind === "tool" && segments[i].callId === ev.tool_call_id) {
          segments[i].status = ev.is_error ? "error" : "ok";
          segments[i].detail = ev.result ?? null;
          segments[i].data = ev.data ?? null;
          if (addArtifactChip) {
            if (_isArtifactToolResult(ev)) {
              addArtifactChip(ev.data.kind, ev.data, { open: true });
            }
            for (const payload of _dataArtifactPayloads(ev)) {
              addArtifactChip("data", payload, { open: false });
            }
          }
          break;
        }
      }
      break;
    }
    case "todo_update": {
      // add_todo 가 누적돼도 todo_update 는 항상 전체 리스트를 보내므로 단일 블록 in-place 갱신.
      let todoIdx = -1;
      for (let i = segments.length - 1; i >= 0; i--) {
        if (segments[i].kind === "todo") { todoIdx = i; break; }
      }
      if (todoIdx >= 0) {
        segments[todoIdx].todos = ev.todos ?? [];
      } else {
        segments.push({ kind: "todo", id: _segId(), todos: ev.todos ?? [], complete: null });
      }
      break;
    }
    case "skill_active": {
      if (setActiveSkills) setActiveSkills(ev.skills ?? []);
      break;
    }
    case "skill_complete": {
      // 해당 scope 의 마지막 todo 세그먼트에 complete 통계를 설정한다.
      const complete = {
        completed: ev.completed ?? 0,
        failed: ev.failed ?? 0,
        skipped: ev.skipped ?? 0,
      };
      for (let i = segments.length - 1; i >= 0; i--) {
        if (segments[i].kind === "todo") {
          segments[i].complete = complete;
          break;
        }
      }
      break;
    }
  }
}
