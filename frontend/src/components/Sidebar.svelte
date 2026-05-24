<script>
  import { ui } from "../lib/state.svelte.js";
  import { createSession, toggleTheme, toggleSidebar } from "../lib/chatActions.svelte.js";
  import { openSettings } from "../lib/settingsActions.svelte.js";
  import { relativeTimeBucket, BUCKET_ORDER } from "../lib/format.js";
  import SessionItem from "./SessionItem.svelte";

  let grouped = $derived.by(() => {
    const buckets = {};
    for (const bucket of BUCKET_ORDER) buckets[bucket] = [];
    const sorted = [...ui.sessions].sort((a, b) => b.updatedAt - a.updatedAt);
    for (const s of sorted) {
      const b = relativeTimeBucket(s.updatedAt);
      (buckets[b] ?? buckets["이전"]).push(s);
    }
    return BUCKET_ORDER.map((bucket) => ({ bucket, items: buckets[bucket] })).filter(
      (g) => g.items.length > 0,
    );
  });

  let isDark = $derived(ui.theme === "dark");
</script>

<aside class="sidebar" class:open={ui.sidebarOpen}>
  <div class="header">
    <div class="brand">
      <span class="logo" aria-hidden="true">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
        </svg>
      </span>
      <span class="brand-text">My Agent</span>
    </div>
    <button class="icon-btn mobile-close" onclick={toggleSidebar} aria-label="사이드바 닫기">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M18 6 6 18" />
        <path d="m6 6 12 12" />
      </svg>
    </button>
  </div>

  <button class="new-btn" onclick={createSession} disabled={ui.streaming}>
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 5v14" />
      <path d="M5 12h14" />
    </svg>
    <span>새 대화</span>
  </button>

  <div class="list">
    {#if grouped.length === 0}
      <div class="empty">아직 대화가 없습니다.</div>
    {:else}
      {#each grouped as group (group.bucket)}
        <div class="group">
          <div class="group-header">{group.bucket}</div>
          {#each group.items as session (session.id)}
            <SessionItem {session} />
          {/each}
        </div>
      {/each}
    {/if}
  </div>

  <div class="footer">
    <button class="footer-btn" onclick={toggleTheme} title="테마 전환">
      {#if isDark}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2" /><path d="M12 20v2" />
          <path d="m4.93 4.93 1.41 1.41" /><path d="m17.66 17.66 1.41 1.41" />
          <path d="M2 12h2" /><path d="M20 12h2" />
          <path d="m6.34 17.66-1.41 1.41" /><path d="m19.07 4.93-1.41 1.41" />
        </svg>
        <span>라이트 모드</span>
      {:else}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
        <span>다크 모드</span>
      {/if}
    </button>

    <button class="footer-icon-btn" onclick={openSettings} title="LLM 설정" aria-label="LLM 설정">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
        <circle cx="12" cy="12" r="3" />
      </svg>
    </button>
  </div>
</aside>

{#if ui.sidebarOpen}
  <button
    class="backdrop"
    onclick={toggleSidebar}
    aria-label="사이드바 닫기"
  ></button>
{/if}

<style>
  .sidebar {
    width: 264px;
    background: var(--bg-elevated);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    height: 100%;
    flex-shrink: 0;
  }

  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 16px 10px;
  }

  .brand {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--fg);
  }

  .logo {
    display: inline-flex;
    color: var(--accent);
  }

  .brand-text {
    font-weight: 600;
    font-size: 15px;
  }

  .mobile-close {
    display: none;
    width: 28px;
    height: 28px;
    border-radius: 6px;
    color: var(--fg-muted);
    align-items: center;
    justify-content: center;
  }

  .mobile-close:hover {
    background: var(--bg-hover);
    color: var(--fg);
  }

  .new-btn {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 4px 12px 12px;
    padding: 9px 12px;
    border: 1px solid var(--border-strong);
    border-radius: 8px;
    color: var(--fg);
    background: var(--bg);
    font-size: 13.5px;
    font-weight: 500;
    transition: background 0.12s ease;
  }

  .new-btn:hover:not(:disabled) {
    background: var(--bg-hover);
  }

  .list {
    flex: 1;
    overflow-y: auto;
    padding: 0 8px 12px;
  }

  .empty {
    padding: 24px 12px;
    color: var(--fg-subtle);
    font-size: 13px;
    text-align: center;
  }

  .group {
    margin-top: 10px;
  }

  .group-header {
    font-size: 11px;
    font-weight: 600;
    color: var(--fg-subtle);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 6px 10px 4px;
  }

  .footer {
    border-top: 1px solid var(--border);
    padding: 10px 12px;
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .footer-btn {
    display: flex;
    align-items: center;
    gap: 10px;
    flex: 1;
    padding: 8px 10px;
    border-radius: 8px;
    color: var(--fg);
    font-size: 13px;
  }

  .footer-btn:hover {
    background: var(--bg-hover);
  }

  .footer-icon-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 34px;
    height: 34px;
    border-radius: 8px;
    color: var(--fg-muted);
    flex-shrink: 0;
  }

  .footer-icon-btn:hover {
    background: var(--bg-hover);
    color: var(--fg);
  }

  .backdrop {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.35);
    z-index: 9;
    border: none;
    cursor: default;
  }

  @media (max-width: 768px) {
    .sidebar {
      position: fixed;
      top: 0;
      left: 0;
      z-index: 11;
      height: 100%;
      transform: translateX(-100%);
      transition: transform 0.18s ease;
      box-shadow: var(--shadow-md);
    }

    .sidebar.open {
      transform: translateX(0);
    }

    .mobile-close {
      display: inline-flex;
    }

    .backdrop {
      display: block;
    }
  }
</style>
