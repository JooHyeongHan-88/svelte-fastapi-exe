<script>
  import { ui, activeSession } from "../lib/state.svelte.js";
  import { toggleSidebar, renameSession } from "../lib/chatActions.svelte.js";
  import { toggleArtifactPanel } from "../lib/artifactActions.svelte.js";
  import ExtensionMenu from "./ExtensionMenu.svelte";

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

  <!-- 우측: 아티팩트 패널 토글 + 확장 런처 드롭다운. 토글은 패널 가시성, 옆 caret 은
       확장 도구를 골라 패널에 연다 (Claude Desktop 의 패널-열기 드롭다운 패턴). -->
  <div class="panel-controls">
    <button
      type="button"
      class="panel-toggle"
      class:active={ui.artifactPanelOpen}
      onclick={toggleArtifactPanel}
      aria-label={ui.artifactPanelOpen ? "아티팩트 패널 닫기" : "아티팩트 패널 열기"}
      aria-pressed={ui.artifactPanelOpen}
      title="아티팩트 패널"
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <rect x="3" y="4" width="18" height="16" rx="2" />
        <path d="M15 4 L 15 20" />
      </svg>
    </button>
    <ExtensionMenu />
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
    border-radius: var(--radius-sm);
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
    border-radius: var(--radius-sm);
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

  .panel-controls {
    display: inline-flex;
    align-items: center;
    gap: 1px;
    flex-shrink: 0;
  }

  /* 아티팩트 패널 토글 — .menu 와 같은 32x32 톤. active 시 accent 음각으로 상태 표시. */
  .panel-toggle {
    display: inline-flex;
    width: 32px;
    height: 32px;
    align-items: center;
    justify-content: center;
    border-radius: var(--radius-sm);
    color: var(--fg-muted);
    background: transparent;
    flex-shrink: 0;
    transition: background var(--dur-fast), color var(--dur-fast);
  }

  .panel-toggle:hover {
    background: var(--bg-hover);
    color: var(--fg);
  }

  .panel-toggle.active {
    background: var(--accent-soft);
    color: var(--accent);
  }

  .panel-toggle.active:hover {
    background: var(--accent-soft-strong);
  }

  .title-input {
    flex: 1;
    background: var(--bg);
    border: 1px solid var(--accent);
    border-radius: var(--radius-sm);
    padding: 4px 8px;
    font-size: 14px;
    font-weight: 600;
    outline: none;
    box-shadow: var(--focus-ring);
    max-width: 480px;
  }

  @media (max-width: 768px) {
    .menu {
      display: inline-flex;
    }
  }
</style>
