// tracer 확장 API fetch 래퍼 — 자체 포함(메인 프론트 lib 에 의존하지 않음).

const BASE = "/api/ext/tracer";

async function toJson(res) {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
    } catch {
      // JSON 본문이 없으면 statusText 유지
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json();
}

/** `_trace/` 가 있는 세션 목록 (최신 트레이스 순). */
export function getSessions() {
  return fetch(`${BASE}/sessions`).then(toJson);
}

/** 한 세션의 턴 트레이스 파일 목록 (최신순). */
export function getTurns(session) {
  return fetch(`${BASE}/turns?${new URLSearchParams({ session })}`).then(toJson);
}

/** 한 턴 트레이스 JSONL → 이벤트 배열. */
export function getTrace(path) {
  return fetch(`${BASE}/trace?${new URLSearchParams({ path })}`).then(toJson);
}
