// 설정 모달 액션. UI 는 이 함수들만 호출한다.

import { ui } from "./state.svelte.js";
import { getSettings, updateSettings, listProviders, testConnection, listModels } from "./settingsApi.js";

// ---------- 모델 Picker ----------

const MODEL_CACHE_TTL_MS = 5 * 60 * 1000; // 5분

export function openModelPicker() {
  if (ui.modelPickerOpen) return;
  ui.modelPickerOpen = true;
  // picker 열릴 때 현재 provider 의 모델 목록 자동 로드
  loadModels(ui.currentProvider);
}

export function closeModelPicker() {
  ui.modelPickerOpen = false;
}

export async function loadModels(provider, { force = false } = {}) {
  if (!provider) return;

  const cached = ui.modelListByProvider[provider];
  if (!force && cached && !cached.loading && Date.now() - cached.loadedAt < MODEL_CACHE_TTL_MS) {
    return;
  }

  ui.modelListByProvider = {
    ...ui.modelListByProvider,
    [provider]: { models: cached?.models ?? [], loading: true, loadedAt: cached?.loadedAt ?? 0 },
  };

  try {
    const { models } = await listModels(provider);
    ui.modelListByProvider = {
      ...ui.modelListByProvider,
      [provider]: { models, loading: false, loadedAt: Date.now() },
    };
  } catch {
    ui.modelListByProvider = {
      ...ui.modelListByProvider,
      [provider]: { models: cached?.models ?? [], loading: false, loadedAt: cached?.loadedAt ?? 0 },
    };
  }
}

export async function selectModel(modelId) {
  if (!modelId) return;
  try {
    await updateSettings({ model: modelId });
    ui.currentModel = modelId;
    ui.modelPickerOpen = false;
  } catch (e) {
    // 저장 실패 시 picker 는 열린 채로 유지하고 에러를 노출한다.
    alert(`모델 변경 실패: ${e?.message ?? e}`);
  }
}

// ---------- 모달 열기/닫기 ----------

export async function openSettings() {
  ui.settingsError = null;
  ui.settingsTestResult = null;

  try {
    const [settings, providers] = await Promise.all([
      getSettings(),
      ui.providers.length ? Promise.resolve(ui.providers) : listProviders(),
    ]);

    if (!ui.providers.length) ui.providers = providers;

    // draft.cache: provider id → 편집 상태.
    // api_key 편집 필드는 빈 칸으로 시작하고, 마스킹된 현재 키는 _maskedKey 에 보관.
    const cache = {};
    for (const p of providers) {
      const stored = settings.providers?.[p.id] ?? {};
      cache[p.id] = {
        model: stored.model ?? "",
        api_key: "",
        _maskedKey: stored.api_key ?? "",
        base_url: stored.base_url ?? "",
        clearKey: false,
      };
    }

    ui.settingsDraft = {
      provider: settings.provider,
      cache,
      // 사용자 지침 — 비어 있지 않으면 토글이 켜진 상태로 시작한다.
      user_prompt: settings.user_prompt ?? "",
      user_prompt_enabled: Boolean(settings.user_prompt),
    };
    ui.settingsOpen = true;
  } catch (e) {
    ui.settingsError = `설정 로드 실패: ${e?.message ?? e}`;
    ui.settingsOpen = true;
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
    const { provider, cache } = ui.settingsDraft;

    // 모든 provider 캐시를 한 번에 저장한다.
    // api_key 처리: clearKey=true → "" (삭제), 입력됨 → 새 값, 아무것도 안 했으면 → null (유지).
    const providers = {};
    for (const [id, cfg] of Object.entries(cache)) {
      let api_key;
      if (cfg.clearKey) {
        api_key = "";
      } else if (cfg.api_key.trim()) {
        api_key = cfg.api_key.trim();
      } else {
        api_key = null;
      }
      providers[id] = { model: cfg.model, api_key, base_url: cfg.base_url };
    }

    // 토글이 OFF 면 빈 문자열로 저장 — 백엔드가 system prompt 합성에서 자연스럽게 스킵.
    // ON 이면 입력값을 2000자로 클램프 (백엔드 max_length=2000 과 정확히 일치).
    const finalUserPrompt = ui.settingsDraft.user_prompt_enabled
      ? (ui.settingsDraft.user_prompt ?? "").slice(0, 2000)
      : "";

    const patch = { provider, providers, user_prompt: finalUserPrompt };
    const updated = await updateSettings(patch);

    // 저장 후 currentModel/currentProvider 동기화
    ui.currentProvider = updated.provider;
    ui.currentModel = updated.providers?.[updated.provider]?.model ?? "";

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
    const { provider, cache } = ui.settingsDraft;
    const cfg = cache[provider] ?? {};
    const effectiveKey = cfg.clearKey ? "" : (cfg.api_key.trim() || "");

    const result = await testConnection({
      provider,
      model: cfg.model,
      api_key: effectiveKey,
      base_url: cfg.base_url,
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
    const [settings, providers] = await Promise.all([getSettings(), listProviders()]);
    ui.providers = providers;
    ui.currentProvider = settings.provider;
    ui.currentModel = settings.providers?.[settings.provider]?.model ?? "";
  } catch {
    // 시작 시 실패해도 사용자에게 즉각 영향 없음 — 모달 열 때 다시 시도됨.
  }
}
