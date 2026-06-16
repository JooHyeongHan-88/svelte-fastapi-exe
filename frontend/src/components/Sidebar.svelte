<script>
  import { ui } from "../lib/state.svelte.js";
  import {
    createSession,
    toggleTheme,
    toggleSidebar,
    toggleSidebarCollapsed,
  } from "../lib/chatActions.svelte.js";
  import { openSettings } from "../lib/settingsActions.svelte.js";
  import { relativeTimeBucket, BUCKET_ORDER } from "../lib/format.js";
  import { saveSidebarWidth, SIDEBAR_WIDTH_BOUNDS } from "../lib/storage.js";
  import SessionItem from "./SessionItem.svelte";
  import ModelPicker from "./ModelPicker.svelte";
  import Logo from "./Logo.svelte";

  let resizing = $state(false);

  function clampWidth(px) {
    const upper = Math.min(
      SIDEBAR_WIDTH_BOUNDS.max,
      Math.floor(window.innerWidth * 0.4),
    );
    return Math.min(upper, Math.max(SIDEBAR_WIDTH_BOUNDS.min, Math.round(px)));
  }

  function onHandlePointerDown(e) {
    if (e.button !== 0) return;
    resizing = true;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    e.preventDefault();
  }

  function onHandlePointerMove(e) {
    if (!resizing) return;
    ui.sidebarWidth = clampWidth(e.clientX);
  }

  function onHandlePointerUp(e) {
    if (!resizing) return;
    resizing = false;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    saveSidebarWidth(ui.sidebarWidth);
  }

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

<aside
  class="sidebar"
  class:open={ui.sidebarOpen}
  class:collapsed={ui.sidebarCollapsed}
  class:resizing
  style="width: {ui.sidebarCollapsed ? 0 : ui.sidebarWidth}px"
>
  <!-- 우측 가장자리 드래그 핸들 -->
  <div
    class="resize-handle"
    role="separator"
    aria-orientation="vertical"
    aria-label="사이드바 너비 조절"
    onpointerdown={onHandlePointerDown}
    onpointermove={onHandlePointerMove}
    onpointerup={onHandlePointerUp}
    onpointercancel={onHandlePointerUp}
  ></div>
  <div class="header">
    <div class="brand">
      <Logo size={20} />
      <div class="brand-text-wrap">
        <span class="brand-text">{ui.appName}</span>
        {#if ui.appVersion}
          <span class="brand-version">v{ui.appVersion}</span>
        {/if}
      </div>
    </div>
    <!-- 데스크탑 전용 접기 버튼 (사이드바 완전 숨김). 모바일은 아래 .mobile-close 사용. -->
    <button class="icon-btn collapse-btn" onclick={toggleSidebarCollapsed} title="사이드바 접기" aria-label="사이드바 접기">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="4" width="18" height="16" rx="2" />
        <path d="M9 4v16" />
        <path d="m15 10-2 2 2 2" />
      </svg>
    </button>
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

  <ModelPicker />

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
    /* width 는 ui.sidebarWidth 로 동적 지정 (접힘 시 0) */
    background: var(--bg-elevated);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    height: 100%;
    flex-shrink: 0;
    position: relative;
    transition: width var(--dur-slow) ease;
  }

  .sidebar.resizing {
    user-select: none;
    cursor: ew-resize;
    transition: none; /* 드래그 중에는 폭 전환 애니메이션 끔 */
  }

  /* 완전 숨김 — 폭 0 + 내용 클립. 채팅(main flex:1)이 빈 폭을 흡수한다. */
  .sidebar.collapsed {
    overflow: hidden;
    border-right: none;
    min-width: 0;
  }

  .sidebar.collapsed .resize-handle {
    display: none;
  }

  .resize-handle {
    position: absolute;
    top: 0;
    right: 0;
    width: 6px;
    height: 100%;
    cursor: ew-resize;
    z-index: 10;
    background: transparent;
    transition: background var(--dur-fast);
    touch-action: none;
  }

  .resize-handle:hover,
  .sidebar.resizing .resize-handle {
    background: var(--accent-border);
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

  .brand-text-wrap {
    display: flex;
    flex-direction: column;
    gap: 1px;
  }

  .brand-text {
    font-weight: 600;
    font-size: 15px;
    line-height: 1.3;
  }

  .brand-version {
    font-size: 10px;
    font-weight: 400;
    color: var(--fg-subtle);
    line-height: 1;
  }

  .mobile-close {
    display: none;
    width: 28px;
    height: 28px;
    border-radius: var(--radius-sm);
    color: var(--fg-muted);
    align-items: center;
    justify-content: center;
  }

  .mobile-close:hover {
    background: var(--bg-hover);
    color: var(--fg);
  }

  /* 데스크탑 전용 접기 버튼 (모바일에선 .mobile-close 가 대신 노출) */
  .collapse-btn {
    display: inline-flex;
    width: 28px;
    height: 28px;
    border-radius: var(--radius-sm);
    color: var(--fg-muted);
    align-items: center;
    justify-content: center;
  }

  .collapse-btn:hover {
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
    border-radius: var(--radius-sm);
    color: var(--fg);
    background: var(--bg);
    font-size: 13.5px;
    font-weight: 500;
    transition: background var(--dur-fast) ease;
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
    border-radius: var(--radius-sm);
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
    width: 32px;
    height: 32px;
    border-radius: var(--radius-sm);
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
    background: var(--backdrop);
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
      width: 264px !important; /* 모바일은 고정 너비 */
      transform: translateX(-100%);
      transition: transform var(--dur-slow) ease;
      box-shadow: var(--shadow-md);
    }

    .resize-handle {
      display: none;
    }

    .sidebar.open {
      transform: translateX(0);
    }

    .mobile-close {
      display: inline-flex;
    }

    .collapse-btn {
      display: none; /* 모바일은 접기 대신 off-canvas(.mobile-close) */
    }

    .backdrop {
      display: block;
    }
  }
</style>
