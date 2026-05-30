// HTTP / SSE 래퍼. fetch 호출은 전부 이 모듈을 통한다 — 컴포넌트는 URL 모름.

const headers = { "Content-Type": "application/json" };

export async function chat(clientId, message, opts = {}) {
  // opts.forceSkills: 슬래시 커맨드로 사용자가 명시한 skill 이름 배열.
  //   백엔드 ChatRequest.force_skills 와 매핑된다 (snake_case 변환).
  // opts.sessionTitle: 세션 제목 — 백엔드가 산출물 폴더명에 사용.
  const body = { message };
  if (opts.forceSkills && opts.forceSkills.length > 0) {
    body.force_skills = opts.forceSkills;
  }
  const params = new URLSearchParams({ client_id: clientId });
  if (opts.sessionTitle) {
    params.set("session_title", opts.sessionTitle);
  }
  return fetch(`/api/chat?${params.toString()}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    // AbortController.signal — ESC 로 응답을 강제 중지할 때 fetch 와 SSE reader 를
    // 동시에 풀어 주는 유일한 진입점.
    signal: opts.signal,
  });
}

export async function listSkills() {
  // 부팅 시 한 번만 호출 — 슬래시 커맨드 autocomplete 데이터.
  try {
    const r = await fetch("/api/skills");
    return r.ok ? r.json() : [];
  } catch {
    return [];
  }
}

export async function deleteConversation(clientId) {
  try {
    await fetch(`/api/conversation?client_id=${clientId}`, { method: "DELETE" });
  } catch {
    // 백엔드 다운 중일 수도 — UI 진행은 막지 않는다.
  }
}

export async function restoreConversation(clientId, messages) {
  // 백엔드 LLM context 가 비어있을 때(EXE 재시작, 세션 전환) localStorage 히스토리를 다시 주입.
  // 매 턴 호출하지 않고, 세션 활성화 시점에 한 번만 호출.
  try {
    await fetch(`/api/conversation/restore?client_id=${clientId}`, {
      method: "POST",
      headers,
      body: JSON.stringify({ messages }),
    });
  } catch {
    // hydrate 실패해도 사용자가 즉시 영향 받지는 않음 — 다음 응답 품질만 떨어짐.
  }
}

export async function checkUpdate() {
  try {
    const r = await fetch("/api/update/check");
    return r.ok ? r.json() : null;
  } catch {
    return null;
  }
}

export async function applyUpdate() {
  const r = await fetch("/api/update/apply", { method: "POST", headers });
  return r.json();
}

export async function getUpdateStatus() {
  const r = await fetch("/api/update/status");
  return r.ok ? r.json() : null;
}

/**
 * 차트 인터랙티브 필터 액션(exclude/undo/redo/reset)을 백엔드에 요청한다.
 * 응답: { items, can_undo, can_redo }
 *
 * @param {{ spec: string, action: string, scope?: string, chart_index?: number, row_ids?: number[] }} body
 */
export async function postChartFilter(body) {
  const r = await fetch("/api/chart/filter", {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    throw new Error(detail || `HTTP ${r.status}`);
  }
  return r.json();
}

/**
 * 라이트박스 오픈 시 undo/redo 초기 상태를 조회한다 (재렌더 없음).
 *
 * @param {string} spec  charts.spec.json 경로 (result/...)
 * @returns {Promise<{ can_undo: boolean, can_redo: boolean }>}
 */
export async function getChartFilterState(spec) {
  try {
    const r = await fetch(
      `/api/chart/filter-state?spec=${encodeURIComponent(spec)}`,
    );
    return r.ok ? r.json() : { can_undo: false, can_redo: false };
  } catch {
    return { can_undo: false, can_redo: false };
  }
}
