// evaluator 확장(별도 탭)이 큐레이션 결과 parquet 을 내보내면, 같은 출처(same-origin)
// 인 이 메인 앱 탭이 BroadcastChannel 로 그 사실을 감지해 해당 세션에 parquet 데이터
// 칩을 붙여 사용자에게 인폼한다.
//
// 칩은 메시지의 artifactChips 에 임베드되므로(localStorage 영속) 새로고침 후에도 남는다.
// 라우팅: 산출물 경로의 세션 폴더는 `core.result_store.session_dir_name` 규약상
// `{title}-{client_id[:8]}` 라, 폴더명 끝 8자(cid8)를 세션 id 앞 8자와 대조해 어느 세션의
// 산출물인지 찾는다(메인 앱이 artifactUsage 를 client_id[:8] 로 키잉하는 것과 동일 패턴).

import { ui } from "./state.svelte.js";
import { makeArtifactChip } from "./artifactActions.svelte.js";
import { saveSessions, saveArtifactPanelOpen } from "./storage.js";

const CHANNEL_NAME = "evaluator:exports";

let channel = null;

/** BroadcastChannel 구독을 시작한다 (initApp 에서 1회 호출). */
export function startEvaluatorBridge() {
  if (channel || typeof BroadcastChannel === "undefined") return;
  try {
    channel = new BroadcastChannel(CHANNEL_NAME);
  } catch {
    channel = null; // 미지원 환경 — 알림 없이 동작(확장 자체는 독립적으로 작동).
    return;
  }
  channel.onmessage = (event) => _handleExport(event.data);
}

/** 구독을 해제한다 (teardown 에서 호출). */
export function stopEvaluatorBridge() {
  if (!channel) return;
  channel.onmessage = null;
  channel.close();
  channel = null;
}

/**
 * 내보내기 알림을 처리해 데이터 칩을 부착한다.
 *
 * @param {{type?:string, session?:string, path?:string, filename?:string, rows?:number, columns?:number}} msg
 */
function _handleExport(msg) {
  if (!msg || msg.type !== "export") return;
  const path = typeof msg.path === "string" ? msg.path : "";
  if (!path.startsWith("result/") || !path.endsWith(".parquet")) return;

  const session = _findSession(msg.session);
  if (!session) return; // 알 수 없는 세션(다른 창/앱의 산출물) — 무시.

  const summary =
    msg.summary && typeof msg.summary === "object" ? msg.summary : undefined;

  // 같은 경로가 이미 칩으로 있으면(중복 브로드캐스트·재내보내기) 요약만 갱신 후 띄운다 —
  // 같은 parquet 을 다시 내보내면 선택/메모가 바뀌었을 수 있으므로 최신 요약을 반영한다.
  if (_hasDataChip(session, path)) {
    _refreshSummary(session, path, summary);
    _focusChip(session, path);
    return;
  }

  const payload = {
    path,
    filename: msg.filename || path.split("/").pop(),
    rows: Number.isFinite(msg.rows) ? msg.rows : undefined,
    columns: Number.isFinite(msg.columns) ? msg.columns : undefined,
    summary,
  };
  const chip = makeArtifactChip("data", payload);

  const target = _targetMessage(session);
  target.artifactChips = [...(target.artifactChips ?? []), chip];
  session.updatedAt = Date.now();

  if (session.id === ui.activeSessionId) {
    ui.activeArtifactId = chip.id;
    ui.artifactPanelOpen = true;
    saveArtifactPanelOpen(true);
  }

  ui.sessions = [...ui.sessions];
  saveSessions(ui.sessions);
}

// 산출물 폴더명(`{title}-{cid8}`)으로 세션을 찾는다. 폴더명 끝 8자(cid8 = 세션 id 앞
// 8자)로 대조하되, 만일 폴더명이 곧 세션 id 인 경우(과거 포맷)도 직접 일치로 처리한다.
function _findSession(folderSeg) {
  if (typeof folderSeg !== "string" || folderSeg.length === 0) return null;
  const direct = ui.sessions.find((s) => s.id === folderSeg);
  if (direct) return direct;
  const cid8 = folderSeg.slice(-8).toLowerCase();
  if (!/^[0-9a-f]{8}$/.test(cid8)) return null;
  return ui.sessions.find((s) => s.id.slice(0, 8).toLowerCase() === cid8) ?? null;
}

function _hasDataChip(session, path) {
  return session.messages.some((m) =>
    (m.artifactChips ?? []).some(
      (c) => c.kind === "data" && c.payload?.path === path,
    ),
  );
}

// 재내보내기 시 기존 칩의 요약을 최신값으로 갱신하고 영속한다(요약 없으면 무변경).
function _refreshSummary(session, path, summary) {
  if (!summary) return;
  for (const m of session.messages) {
    for (const c of m.artifactChips ?? []) {
      if (c.kind === "data" && c.payload?.path === path) {
        c.payload.summary = summary;
        ui.sessions = [...ui.sessions];
        saveSessions(ui.sessions);
        return;
      }
    }
  }
}

function _focusChip(session, path) {
  if (session.id !== ui.activeSessionId) return;
  for (const m of session.messages) {
    for (const c of m.artifactChips ?? []) {
      if (c.kind === "data" && c.payload?.path === path) {
        ui.activeArtifactId = c.id;
        ui.artifactPanelOpen = true;
        saveArtifactPanelOpen(true);
        return;
      }
    }
  }
}

// 칩을 붙일 대상 메시지 — 마지막 어시스턴트 메시지(open_curation 카드가 있는 턴)를
// 우선한다. 없으면(드묾) 알림용 경량 어시스턴트 메시지를 만든다.
function _targetMessage(session) {
  for (let i = session.messages.length - 1; i >= 0; i--) {
    if (session.messages[i].role === "assistant") return session.messages[i];
  }
  const now = Date.now();
  const note = "큐레이션 결과를 내보냈습니다.";
  session.messages = [
    ...session.messages,
    {
      id: crypto.randomUUID(),
      role: "assistant",
      content: note,
      segments: [{ kind: "text", id: crypto.randomUUID().slice(0, 8), content: note }],
      activeSkills: null,
      askUser: null,
      artifactChips: [],
      isStopped: false,
      isFallback: false,
      createdAt: now,
      streaming: false,
      startedAt: now,
      finishedAt: now,
      durationMs: 0,
    },
  ];
  return session.messages[session.messages.length - 1];
}
