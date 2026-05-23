<script>
  import { ui } from "../lib/state.svelte.js";
  import { closeUpdateModal } from "../lib/chatActions.svelte.js";

  let pct = $derived.by(() => {
    const s = ui.applyState;
    if (!s || !s.total) return 0;
    return Math.min(100, Math.round((s.progress / s.total) * 100));
  });
</script>

{#if ui.modalOpen}
  <div class="backdrop" role="presentation">
    <div class="modal" role="dialog" aria-modal="true">
      {#if ui.restarting}
        <h3>재시작 중…</h3>
        <p>새 버전으로 교체 후 자동으로 다시 열립니다.</p>
      {:else if ui.applyState?.status === "error"}
        <h3>업데이트 실패</h3>
        <p class="error">{ui.applyState.message}</p>
        <div class="actions">
          <button class="primary" onclick={closeUpdateModal}>닫기</button>
        </div>
      {:else}
        <h3>업데이트 진행 중</h3>
        <p class="muted">{ui.applyState?.message ?? ""}</p>
        <div class="progress">
          <div class="bar" style="width: {pct}%"></div>
        </div>
        <small class="muted">{ui.applyState?.status ?? ""}</small>
      {/if}
    </div>
  </div>
{/if}

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 30;
  }

  .modal {
    background: var(--bg);
    color: var(--fg);
    padding: 24px;
    border-radius: 14px;
    min-width: 360px;
    max-width: 480px;
    box-shadow: var(--shadow-md);
    border: 1px solid var(--border);
  }

  h3 {
    margin: 0 0 8px;
    font-size: 16px;
  }

  p {
    margin: 0;
    font-size: 13.5px;
  }

  .muted {
    color: var(--fg-muted);
  }

  .error {
    color: var(--danger);
  }

  .progress {
    width: 100%;
    height: 8px;
    background: var(--bg-elevated);
    border-radius: 4px;
    overflow: hidden;
    margin: 14px 0 6px;
  }

  .bar {
    height: 100%;
    background: var(--accent);
    transition: width 0.2s ease;
  }

  small {
    font-size: 11.5px;
  }

  .actions {
    display: flex;
    justify-content: flex-end;
    margin-top: 14px;
  }

  .primary {
    padding: 7px 14px;
    border-radius: 8px;
    background: var(--accent);
    color: var(--accent-fg);
    font-weight: 500;
  }

  .primary:hover {
    background: var(--accent-hover);
  }
</style>
