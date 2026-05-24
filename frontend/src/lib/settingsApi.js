// Settings API 래퍼. /api/settings/* 엔드포인트만 담당한다.

const h = { "Content-Type": "application/json" };

/** 현재 저장된 설정 조회 (api_key는 마스킹된 값으로 반환). */
export async function getSettings() {
  const r = await fetch("/api/settings");
  if (!r.ok) throw new Error(`settings fetch failed: ${r.status}`);
  return r.json();
}

/**
 * 설정 부분 업데이트.
 * @param {object} patch - 변경할 필드만 포함 (api_key=null 이면 변경 없음, ""이면 삭제).
 * @returns {Promise<object>} 저장 후 설정 (api_key 마스킹됨).
 */
export async function updateSettings(patch) {
  const r = await fetch("/api/settings", {
    method: "POST",
    headers: h,
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error(`settings update failed: ${r.status}`);
  return r.json();
}

/** 프로바이더 목록 (ProviderMeta[]) 조회. */
export async function listProviders() {
  const r = await fetch("/api/settings/providers");
  if (!r.ok) throw new Error(`providers fetch failed: ${r.status}`);
  return r.json();
}

/**
 * 연결 테스트 (저장 없이 임시 설정으로 ping).
 * api_key가 비어 있으면 백엔드가 저장된 키를 fallback으로 사용한다.
 */
export async function testConnection({ provider, model, api_key, base_url }) {
  const r = await fetch("/api/settings/test", {
    method: "POST",
    headers: h,
    body: JSON.stringify({ provider, model, api_key: api_key ?? "", base_url: base_url ?? "" }),
  });
  if (!r.ok) throw new Error(`connection test failed: ${r.status}`);
  return r.json();
}
