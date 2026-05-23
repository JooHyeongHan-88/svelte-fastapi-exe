<script>
  import { ui, activeSession } from "../lib/state.svelte.js";
  import { toggleSidebar, renameSession } from "../lib/chatActions.svelte.js";

  let session = $derived(activeSession());
  let title = $derived(session?.title ?? "새 대화");

  let editing = $state(false);
  let draft = $state("");
  let inputEl = $state(null);

  function startEdit() {
    if (!session) return;
    draft = title;
    editing = true;
    queueMicrotask(() => {
      inputEl?.focus();
      inputEl?.select();
    });
  }

  function commit() {
    if (!editing) return;
    if (session && draft.trim() && draft.trim() !== session.title) {
      renameSession(session.id, draft);
    }
    editing = false;
  }

  function onKey(e) {
    if (e.key === "Enter") {
      e.preventDefault();
      commit();
    } else if (e.key === "Escape") {
      editing = false;
    }
  }
</script>

<header class="topbar">
  <button class="menu" onclick={toggleSidebar} aria-label="사이드바">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M3 12h18" />
      <path d="M3 6h18" />
      <path d="M3 18h18" />
    </svg>
  </button>

  <div class="title-wrap">
    {#if editing}
      <input
        bind:this={inputEl}
        bind:value={draft}
        onkeydown={onKey}
        onblur={commit}
        class="title-input"
      />
    {:else}
      <button class="title-btn" onclick={startEdit} disabled={!session} title="제목 편집">
        {title}
      </button>
    {/if}
  </div>
</header>

<style>
  .topbar {
    display: flex;
    align-items: center;
    gap: 8px;
    height: 48px;
    padding: 0 16px;
    border-bottom: 1px solid var(--border);
    background: var(--bg);
  }

  .menu {
    display: none;
    width: 32px;
    height: 32px;
    align-items: center;
    justify-content: center;
    border-radius: 7px;
    color: var(--fg-muted);
  }

  .menu:hover {
    background: var(--bg-hover);
    color: var(--fg);
  }

  .title-wrap {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
  }

  .title-btn {
    max-width: 100%;
    padding: 4px 8px;
    border-radius: 6px;
    font-size: 14px;
    font-weight: 600;
    color: var(--fg);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .title-btn:hover:not(:disabled) {
    background: var(--bg-hover);
  }

  .title-input {
    flex: 1;
    background: var(--bg);
    border: 1px solid var(--accent);
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 14px;
    font-weight: 600;
    outline: none;
    max-width: 480px;
  }

  @media (max-width: 768px) {
    .menu {
      display: inline-flex;
    }
  }
</style>
