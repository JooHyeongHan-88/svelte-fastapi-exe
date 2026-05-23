// HTTP / SSE 래퍼. fetch 호출은 전부 이 모듈을 통한다 — 컴포넌트는 URL 모름.

const headers = { "Content-Type": "application/json" };

export async function chat(clientId, message) {
  return fetch(`/api/chat?client_id=${clientId}`, {
    method: "POST",
    headers,
    body: JSON.stringify({ message }),
  });
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
