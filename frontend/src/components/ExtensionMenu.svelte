<script>
  // 패널 열기 버튼에 붙는 확장 런처 드롭다운 (Claude Desktop 패턴 차용).
  // ui.extensions(=/api/extensions) 을 나열해, 고르면 확장을 우측 패널에 iframe 으로 연다.
  // 확장이 하나도 없으면 caret 자체를 숨긴다.
  import { ui } from "../lib/state.svelte.js";
  import {
    toggleExtensionMenu,
    closeExtensionMenu,
    openExtensionPanel,
  } from "../lib/artifactActions.svelte.js";
  import ArtifactIcon from "./ArtifactIcon.svelte";

  function onKeydown(e) {
    if (e.key === "Escape") closeExtensionMenu();
  }
</script>

<svelte:window onkeydown={onKeydown} />

{#if ui.extensions.length > 0}
  <div class="ext-launch">
    <button
      type="button"
      class="caret-btn"
      class:active={ui.extensionMenuOpen}
      onclick={toggleExtensionMenu}
      aria-expanded={ui.extensionMenuOpen}
      aria-haspopup="menu"
      aria-label="확장 도구 열기"
      title="확장 도구 열기"
    >
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="m6 9 6 6 6-6" />
      </svg>
    </button>

    {#if ui.extensionMenuOpen}
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <div class="backdrop" onclick={closeExtensionMenu}></div>

      <div class="popup" role="menu" aria-label="확장 도구">
        <div class="popup-header">확장 도구</div>
        <div class="ext-list">
          {#each ui.extensions as ext (ext.tool)}
            <button
              class="ext-item"
              role="menuitem"
              onclick={() => openExtensionPanel(ext.tool)}
              title={ext.description || ext.name}
            >
              <span class="ext-icon"><ArtifactIcon kind="extension" size={15} /></span>
              <span class="ext-text">
                <span class="ext-name">{ext.name}</span>
                {#if ext.description}
                  <span class="ext-desc">{ext.description}</span>
                {/if}
              </span>
            </button>
          {/each}
        </div>
      </div>
    {/if}
  </div>
{/if}

<style>
  .ext-launch {
    position: relative;
    display: inline-flex;
    flex-shrink: 0;
  }

  .caret-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 32px;
    border-radius: var(--radius-sm);
    color: var(--fg-subtle);
    background: transparent;
    transition: background var(--dur-fast), color var(--dur-fast);
  }

  .caret-btn:hover {
    background: var(--bg-hover);
    color: var(--fg);
  }

  .caret-btn.active {
    background: var(--accent-soft);
    color: var(--accent);
  }

  .backdrop {
    position: fixed;
    inset: 0;
    z-index: 19;
  }

  .popup {
    position: absolute;
    top: calc(100% + 6px);
    right: 0;
    width: 260px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-md);
    z-index: 20;
    display: flex;
    flex-direction: column;
    max-height: 360px;
    overflow: hidden;
    animation: ext-popup-in var(--dur-fast) ease;
  }

  @keyframes ext-popup-in {
    from {
      opacity: 0;
      transform: translateY(-6px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  .popup-header {
    padding: 10px 12px 8px;
    border-bottom: 1px solid var(--border);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--fg-subtle);
    flex-shrink: 0;
  }

  .ext-list {
    overflow-y: auto;
    padding: 4px;
  }

  .ext-item {
    display: flex;
    align-items: flex-start;
    gap: 9px;
    width: 100%;
    padding: 8px 10px;
    border-radius: var(--radius-sm);
    text-align: left;
    color: var(--fg);
    transition: background var(--dur-fast);
  }

  .ext-item:hover {
    background: var(--bg-hover);
  }

  .ext-icon {
    display: inline-flex;
    margin-top: 1px;
    color: var(--accent);
    flex-shrink: 0;
  }

  .ext-text {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .ext-name {
    font-size: 13px;
    font-weight: 600;
  }

  .ext-desc {
    font-size: 11.5px;
    color: var(--fg-muted);
    line-height: 1.35;
  }
</style>
