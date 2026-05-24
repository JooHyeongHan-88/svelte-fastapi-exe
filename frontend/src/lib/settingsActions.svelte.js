// 설정 모달 액션. UI 는 이 함수들만 호출한다.

import { ui } from "./state.svelte.js";
import { getSettings, updateSettings, listProviders, testConnection } from "./settingsApi.js";

// ---------- 모달 열기/닫기 ----------

export async function openSettings() {
  ui.settingsError = null;
  ui.settingsTestResult = null;

  try {
    // 이미 providers 목록이 있으면 재사용.
    const [settings, providers] = await Promise.all([
      getSettings(),
      ui.providers.length ? Promise.resolve(ui.providers) : listProviders(),
    ]);

    if (!ui.providers.length) ui.providers = providers;

    // draft: api_key 편집 필드는 빈 칸으로 시작, 마스킹된 현재 키는 _maskedKey에 보관.
    ui.settingsDraft = {
      provider: settings.provider,
      model: settings.model,
      api_key: "",
      _maskedKey: settings.api_key ?? "",
      base_url: settings.base_url ?? "",
      clearKey: false,
    };
    ui.settingsOpen = true;
  } catch (e) {
    ui.settingsError = `설정 로드 실패: ${e?.message ?? e}`;
    ui.settingsOpen = true; // 오류 메시지와 함께 모달 열기
  }
}

export function closeSettings() {
  if (ui.settingsSaving) return;
  ui.settingsOpen = false;
  ui.settingsDraft = null;
  ui.settingsError = null;
  ui.settingsTestResult = null;
}

// ---------- 저장 ----------

export async function saveSettings() {
  if (!ui.settingsDraft || ui.settingsSaving) return;
  ui.settingsSaving = true;
  ui.settingsError = null;

  try {
    const d = ui.settingsDraft;
    const patch = {
      provider: d.provider,
      model: d.model,
      base_url: d.base_url,
      // temperature, max_tokens, system_prompt 는 config.py / 환경 변수로 관리 — UI 에서 덮어쓰지 않음.
    };

    // API 키 처리:
    //  clearKey=true  → "" (키 삭제)
    //  api_key에 값 입력됨 → 새 키로 교체
    //  아무것도 안 했으면 → null (백엔드가 무시 = 기존 키 유지)
    if (d.clearKey) {
      patch.api_key = "";
    } else if (d.api_key.trim()) {
      patch.api_key = d.api_key.trim();
    } else {
      patch.api_key = null;
    }

    await updateSettings(patch);
    ui.settingsOpen = false;
    ui.settingsDraft = null;
  } catch (e) {
    ui.settingsError = `저장 실패: ${e?.message ?? e}`;
  } finally {
    ui.settingsSaving = false;
  }
}

// ---------- 연결 테스트 ----------

export async function testConnectionAction() {
  if (!ui.settingsDraft || ui.settingsTesting) return;
  ui.settingsTesting = true;
  ui.settingsTestResult = null;

  try {
    const d = ui.settingsDraft;
    // api_key가 입력된 경우 그 키로, 아니면 빈 문자열을 전달.
    // 백엔드에서 빈 문자열이 오면 저장된 키를 fallback으로 사용한다.
    const effectiveKey = d.clearKey ? "" : (d.api_key.trim() || "");

    const result = await testConnection({
      provider: d.provider,
      model: d.model,
      api_key: effectiveKey,
      base_url: d.base_url,
    });
    ui.settingsTestResult = result;
  } catch (e) {
    ui.settingsTestResult = { ok: false, message: String(e) };
  } finally {
    ui.settingsTesting = false;
  }
}

// ---------- 앱 시작 시 초기 로드 ----------

export async function loadSettingsForInit() {
  try {
    const [, providers] = await Promise.all([getSettings(), listProviders()]);
    ui.providers = providers;
  } catch {
    // 시작 시 실패해도 사용자에게 즉각 영향 없음 — 모달 열 때 다시 시도됨.
  }
}
