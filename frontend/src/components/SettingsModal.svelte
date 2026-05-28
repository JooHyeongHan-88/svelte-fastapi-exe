<script>
  import { ui } from "../lib/state.svelte.js";
  import {
    closeSettings,
    saveSettings,
    testConnectionAction,
  } from "../lib/settingsActions.svelte.js";

  // 현재 선택된 프로바이더의 메타 정보
  let meta = $derived(
    ui.providers.find((p) => p.id === ui.settingsDraft?.provider) ?? null,
  );

  // 현재 선택된 프로바이더의 draft 캐시 슬롯
  let cfg = $derived(
    ui.settingsDraft?.cache?.[ui.settingsDraft?.provider] ?? null,
  );

  function onBackdrop(e) {
    if (e.target === e.currentTarget) closeSettings();
  }

  function onKeydown(e) {
    if (e.key === "Escape" && !ui.settingsSaving) closeSettings();
  }

  function onProviderChange(e) {
    ui.settingsDraft.provider = e.target.value;
    ui.settingsTestResult = null;
  }
</script>

<svelte:window onkeydown={onKeydown} />

{#if ui.settingsOpen && ui.settingsDraft}
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <div class="overlay" role="presentation" onclick={onBackdrop}>
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="settings-title">

      <!-- ── 헤더 ── -->
      <div class="modal-header">
        <h2 class="modal-title" id="settings-title">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
            <circle cx="12" cy="12" r="3" />
          </svg>
          LLM 설정
        </h2>
        <button
          class="icon-btn"
          onclick={closeSettings}
          disabled={ui.settingsSaving}
          aria-label="닫기"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M18 6 6 18" />
            <path d="m6 6 12 12" />
          </svg>
        </button>
      </div>

      <!-- ── 본문 ── -->
      <div class="modal-body">

        <!-- 프로바이더 섹션 -->
        <section class="section">
          <div class="section-label">프로바이더</div>

          <div class="field">
            <label class="field-label" for="s-provider">프로바이더</label>
            <select
              id="s-provider"
              class="select"
              value={ui.settingsDraft.provider}
              onchange={onProviderChange}
              disabled={ui.settingsSaving}
            >
              {#each ui.providers as p (p.id)}
                <option value={p.id}>{p.label}</option>
              {/each}
            </select>
            {#if meta?.docs_url}
              <a class="docs-link" href={meta.docs_url} target="_blank" rel="noopener noreferrer">
                문서 보기 ↗
              </a>
            {/if}
          </div>

          {#if cfg && meta?.requires_model}
            <div class="field">
              <label class="field-label" for="s-model">모델</label>
              <input
                id="s-model"
                class="input"
                type="text"
                bind:value={cfg.model}
                placeholder={meta.suggested_models[0] ?? "모델명 입력"}
                list="s-model-hints"
                disabled={ui.settingsSaving}
              />
              {#if meta.suggested_models.length}
                <datalist id="s-model-hints">
                  {#each meta.suggested_models as m (m)}
                    <option value={m}></option>
                  {/each}
                </datalist>
              {/if}
            </div>
          {/if}

          {#if cfg && meta?.requires_api_key}
            <div class="field">
              <label class="field-label" for="s-apikey">API 키</label>
              <input
                id="s-apikey"
                class="input"
                type="password"
                bind:value={cfg.api_key}
                placeholder={cfg._maskedKey
                  ? "변경하려면 새 키 입력 (비워두면 유지)"
                  : "sk-xxx..."}
                autocomplete="new-password"
                disabled={ui.settingsSaving || cfg.clearKey}
              />
              {#if cfg._maskedKey && !cfg.clearKey}
                <p class="field-hint">
                  현재 설정됨: <code class="masked">{cfg._maskedKey}</code>
                  <button
                    type="button"
                    class="link-btn danger-link"
                    onclick={() => {
                      cfg.clearKey = true;
                      cfg.api_key = "";
                    }}
                  >키 삭제</button>
                </p>
              {/if}
              {#if cfg.clearKey}
                <p class="field-hint danger-hint">
                  ⚠ 저장 시 API 키가 삭제됩니다.
                  <button
                    type="button"
                    class="link-btn"
                    onclick={() => (cfg.clearKey = false)}
                  >취소</button>
                </p>
              {/if}
            </div>
          {/if}

          {#if cfg && meta?.requires_base_url}
            <div class="field">
              <label class="field-label" for="s-baseurl">Base URL</label>
              <input
                id="s-baseurl"
                class="input"
                type="url"
                bind:value={cfg.base_url}
                placeholder="http://localhost:11434/v1"
                disabled={ui.settingsSaving}
              />
              <p class="field-hint">OpenAI 호환 엔드포인트 (Ollama, vLLM, LM Studio 등)</p>
            </div>
          {/if}
        </section>

        <!-- 사용자 지침 섹션 — 시스템 프롬프트 뒤에 합성될 추가 지침. -->
        <section class="section">
          <div class="section-label">사용자 지침</div>

          <label class="toggle-row">
            <input
              type="checkbox"
              bind:checked={ui.settingsDraft.user_prompt_enabled}
              disabled={ui.settingsSaving}
            />
            <span>시스템 프롬프트에 사용자 지침을 추가</span>
          </label>

          {#if ui.settingsDraft.user_prompt_enabled}
            <div class="field user-prompt-field">
              <textarea
                class="textarea"
                bind:value={ui.settingsDraft.user_prompt}
                maxlength="2000"
                rows="5"
                placeholder="예: 모든 코드 예시는 TypeScript로 작성하고, 응답 마지막에 한 줄 요약을 붙여주세요"
                disabled={ui.settingsSaving}
              ></textarea>
              <div
                class="char-count"
                class:warn={(ui.settingsDraft.user_prompt?.length ?? 0) > 1500}
              >
                {ui.settingsDraft.user_prompt?.length ?? 0} / 2000
              </div>
            </div>
          {/if}
        </section>

      </div>

      <!-- ── 푸터 ── -->
      <div class="modal-footer">
        {#if ui.settingsError}
          <div class="error-msg" role="alert">{ui.settingsError}</div>
        {/if}

        <div class="footer-row">
          <!-- 연결 테스트 -->
          <div class="test-area">
            <button
              type="button"
              class="btn-outline"
              onclick={testConnectionAction}
              disabled={ui.settingsTesting || ui.settingsSaving}
            >
              {#if ui.settingsTesting}
                <span class="spinner" aria-hidden="true"></span>테스트 중…
              {:else}
                연결 테스트
              {/if}
            </button>

            {#if ui.settingsTestResult}
              <span
                class="test-result"
                class:success={ui.settingsTestResult.ok}
                class:failure={!ui.settingsTestResult.ok}
                role="status"
              >
                {ui.settingsTestResult.ok ? "✓" : "✗"}
                {ui.settingsTestResult.message}
                {#if ui.settingsTestResult.ok && ui.settingsTestResult.latency_ms != null}
                  ({Math.round(ui.settingsTestResult.latency_ms)}ms)
                {/if}
              </span>
            {/if}
          </div>

          <!-- 저장/취소 -->
          <div class="btn-group">
            <button
              type="button"
              class="btn-ghost"
              onclick={closeSettings}
              disabled={ui.settingsSaving}
            >취소</button>
            <button
              type="button"
              class="btn-primary"
              onclick={saveSettings}
              disabled={ui.settingsSaving}
            >
              {ui.settingsSaving ? "저장 중…" : "저장"}
            </button>
          </div>
        </div>
      </div>

    </div>
  </div>
{/if}

<style>
  /* ── Overlay ── */
  .overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.45);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 40;
    padding: 16px;
  }

  /* ── Modal container ── */
  .modal {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-md);
    width: 100%;
    max-width: 520px;
    max-height: calc(100dvh - 32px);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  /* ── Header ── */
  .modal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }

  .modal-title {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 0;
    font-size: 15px;
    font-weight: 600;
    color: var(--fg);
  }

  .icon-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    border-radius: var(--radius-sm);
    color: var(--fg-muted);
    flex-shrink: 0;
  }

  .icon-btn:hover:not(:disabled) {
    background: var(--bg-hover);
    color: var(--fg);
  }

  /* ── Body ── */
  .modal-body {
    flex: 1;
    overflow-y: auto;
    padding: 0 20px;
  }

  .section {
    padding: 16px 0;
    border-bottom: 1px solid var(--border);
  }

  .section:last-child {
    border-bottom: none;
  }

  .section-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--fg-subtle);
    margin-bottom: 12px;
  }

  /* ── Fields ── */
  .field {
    margin-bottom: 14px;
  }

  .field:last-child {
    margin-bottom: 0;
  }

  .field-label {
    display: block;
    font-size: 13px;
    font-weight: 500;
    color: var(--fg-muted);
    margin-bottom: 5px;
  }

  .field-hint {
    margin: 4px 0 0;
    font-size: 12px;
    color: var(--fg-subtle);
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }

  .danger-hint {
    color: var(--danger);
  }

  .masked {
    font-family: var(--font-mono);
    font-size: 11.5px;
    background: var(--code-inline-bg);
    padding: 1px 5px;
    border-radius: 4px;
  }

  /* ── Inputs ── */
  .input,
  .select {
    width: 100%;
    padding: 8px 10px;
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-sm);
    background: var(--bg);
    color: var(--fg);
    font-size: 13.5px;
    transition: border-color 0.12s;
    outline: none;
  }

  .input:focus,
  .select:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 15%, transparent);
  }

  .input:disabled,
  .select:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }

  .select {
    cursor: pointer;
    appearance: auto;
  }

  /* ── 사용자 지침 ── */
  .toggle-row {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: var(--fg);
    cursor: pointer;
    user-select: none;
  }

  .toggle-row input[type="checkbox"] {
    cursor: pointer;
  }

  .user-prompt-field {
    margin-top: 10px;
  }

  .textarea {
    width: 100%;
    padding: 8px 10px;
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-sm);
    background: var(--bg);
    color: var(--fg);
    font-size: 13px;
    font-family: inherit;
    line-height: 1.5;
    resize: vertical;
    min-height: 100px;
    outline: none;
    transition: border-color 0.12s;
  }

  .textarea:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 15%, transparent);
  }

  .textarea:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }

  .char-count {
    text-align: right;
    font-size: 11px;
    color: var(--fg-subtle);
    margin-top: 4px;
  }

  .char-count.warn {
    color: var(--danger);
  }

  .docs-link {
    display: inline-block;
    margin-top: 4px;
    font-size: 12px;
    color: var(--accent);
    text-decoration: none;
  }

  .docs-link:hover {
    text-decoration: underline;
  }

  /* ── Link buttons ── */
  .link-btn {
    font-size: 12px;
    color: var(--accent);
    text-decoration: underline;
    padding: 0;
    cursor: pointer;
  }

  .danger-link {
    color: var(--danger);
  }

  /* ── Footer ── */
  .modal-footer {
    padding: 14px 20px;
    border-top: 1px solid var(--border);
    flex-shrink: 0;
  }

  .error-msg {
    font-size: 12.5px;
    color: var(--danger);
    background: var(--danger-bg);
    border-radius: var(--radius-sm);
    padding: 8px 10px;
    margin-bottom: 12px;
  }

  .footer-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
  }

  .test-area {
    display: flex;
    align-items: center;
    gap: 10px;
    flex: 1;
    min-width: 0;
  }

  .test-result {
    font-size: 12px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .test-result.success {
    color: var(--color-success);
  }

  .test-result.failure {
    color: var(--danger);
  }

  .btn-group {
    display: flex;
    gap: 8px;
    flex-shrink: 0;
  }

  /* ── Buttons ── */
  .btn-outline,
  .btn-ghost,
  .btn-primary {
    padding: 7px 14px;
    border-radius: var(--radius-sm);
    font-size: 13px;
    font-weight: 500;
    transition:
      background 0.1s,
      border-color 0.1s;
    white-space: nowrap;
    cursor: pointer;
  }

  .btn-outline {
    border: 1px solid var(--border-strong);
    color: var(--fg);
  }

  .btn-outline:hover:not(:disabled) {
    background: var(--bg-hover);
  }

  .btn-ghost {
    color: var(--fg-muted);
  }

  .btn-ghost:hover:not(:disabled) {
    background: var(--bg-hover);
    color: var(--fg);
  }

  .btn-primary {
    background: var(--accent);
    color: var(--accent-fg);
  }

  .btn-primary:hover:not(:disabled) {
    background: var(--accent-hover);
  }

  .btn-outline:disabled,
  .btn-ghost:disabled,
  .btn-primary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  /* ── Spinner ── */
  .spinner {
    display: inline-block;
    width: 12px;
    height: 12px;
    border: 2px solid currentColor;
    border-top-color: transparent;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    margin-right: 5px;
    vertical-align: middle;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
</style>
