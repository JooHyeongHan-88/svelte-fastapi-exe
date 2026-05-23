<script>
  import { ui } from "../lib/state.svelte.js";
  import { startUpdate, dismissUpdate } from "../lib/chatActions.svelte.js";

  let visible = $derived(
    ui.updateInfo?.update_available && !ui.updateDismissed && !ui.modalOpen,
  );
</script>

{#if visible}
  <div class="banner">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
    <span>
      새 버전 <b>{ui.updateInfo.latest}</b> 사용 가능 (현재 {ui.updateInfo.current})
    </span>
    <button class="primary" onclick={startUpdate}>지금 업데이트</button>
    <button class="ghost" onclick={dismissUpdate}>나중에</button>
  </div>
{/if}

<style>
  .banner {
    position: fixed;
    top: 12px;
    right: 12px;
    z-index: 20;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
    background: var(--accent);
    color: var(--accent-fg);
    border-radius: 10px;
    font-size: 13px;
    box-shadow: var(--shadow-md);
  }

  .primary {
    padding: 5px 12px;
    border-radius: 6px;
    background: var(--bg);
    color: var(--accent);
    font-weight: 600;
  }

  .primary:hover {
    background: var(--bg-elevated);
  }

  .ghost {
    padding: 5px 10px;
    border-radius: 6px;
    background: transparent;
    color: var(--accent-fg);
    border: 1px solid color-mix(in srgb, var(--accent-fg) 50%, transparent);
  }

  .ghost:hover {
    background: color-mix(in srgb, var(--accent-fg) 12%, transparent);
  }
</style>
