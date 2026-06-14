// evaluator 확장 API fetch 래퍼 — 자체 포함(메인 프론트 lib 에 의존하지 않음).
// 컴포넌트는 URL 을 직접 모르고 이 함수들만 호출한다.

const BASE = "/api/ext/evaluator";

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

function postJson(path, body) {
  return fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(toJson);
}

/** 소스 parquet → 선택 항목 리스트 + scatter 포인트. mapping 은 비어있어도 됨(백엔드 기본값). */
export function getDataset(path, mapping = {}) {
  const params = new URLSearchParams({ path });
  for (const [key, value] of Object.entries(mapping)) {
    if (value) params.set(key, value);
  }
  return fetch(`${BASE}/dataset?${params}`).then(toJson);
}

/** 현재 소스가 속한 세션의 parquet 후보 목록 (소스 추가 picker 카탈로그). */
export function getSources(path) {
  return fetch(`${BASE}/sources?${new URLSearchParams({ path })}`).then(toJson);
}

/** parquet head(N) 미리보기 — 피커에서 어떤 소스를 고를지 판단하는 용도. */
export function getPreview(path, rows = 10) {
  return fetch(
    `${BASE}/preview?${new URLSearchParams({ path, rows: String(rows) })}`,
  ).then(toJson);
}

/** 저장된 큐레이션 상태(선택·순서) 로드. */
export function getState(path) {
  return fetch(`${BASE}/state?${new URLSearchParams({ path })}`).then(toJson);
}

/** 큐레이션 상태 저장 (저장하기). */
export function saveState(path, selected, order) {
  return postJson("/state", { path, selected, order });
}

/**
 * 선택 항목만 필터 + 차트 Filter 제외 반영 + rank 재계산 → 새 parquet (내보내기).
 *
 * @param {string} path
 * @param {string[]} selected  최종 리스트 순서대로의 선택키
 * @param {object} mapping
 * @param {Record<string, number[]>} excluded  선택키별 제외 point 인덱스(차트 Filter)
 */
export function exportCurated(path, selected, mapping = {}, excluded = {}) {
  return postJson("/export", { path, selected, mapping, excluded });
}
