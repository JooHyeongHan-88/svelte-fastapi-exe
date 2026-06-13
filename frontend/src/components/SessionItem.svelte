<script>
  import { ui } from "../lib/state.svelte.js";
  import { selectSession, deleteSession, renameSession } from "../lib/chatActions.svelte.js";
  import { formatBytes } from "../lib/format.js";

  let { session } = $props();

  let editing = $state(false);
  let draft = $state("");
  let inputEl = $state(null);

  let isActive = $derived(ui.activeSessionId === session.id);

  // 이 세션 산출물 총 용량 — 세션 id 앞 8자(폴더 접미사)로 조회. 0 이면 라벨이 ""(미표시).
  let usageBytes = $derived(ui.artifactUsage[session.id.slice(0, 8)] ?? 0);
  let usageLabel = $derived(formatBytes(usageBytes));

  function onSelect() {
    if (editing) return;
    selectSession(session.id);
  }

  function startEdit(e) {
    e.stopPropagation();
    draft = session.title;
    editing = true;
    queueMicrotask(() => {
      inputEl?.focus();
      inputEl?.select();
    });
  }

  function commitEdit() {
    if (!editing) return;
    if (draft.trim() && draft.trim() !== session.title) {
      renameSession(session.id, draft);
    }
    editing = false;
  }

  function cancelEdit() {
    editing = false;
  }

  function onKey(e) {
    if (e.key === "Enter") {
      e.preventDefault();
      commitEdit();
    } else if (e.key === "Escape") {
      cancelEdit();
    }
  }

  function onDelete(e) {
    e.stopPropagation();
    const note =
      usageBytes > 0
        ? `\n\n이 대화에서 생성된 산출물(${usageLabel})도 함께 삭제됩니다.`
        : "\n\n이 대화에서 생성된 산출물도 함께 삭제됩니다.";
    if (confirm(`"${session.title}" 대화를 삭제할까요?${note}`)) {
      deleteSession(session.id);
    }
  }
</script>

<div
  class="row"
  class:active={isActive}
  role="button"
  tabindex="0"
  onclick={onSelect}
  ondblclick={startEdit}
  onkeydown={(e) => e.key === "Enter" && onSelect()}
>
  {#if editing}
    <input
      bind:this={inputEl}
      bind:value={draft}
      onkeydown={onKey}
      onblur={commitEdit}
      class="edit"
    />
  {:else}
    <span class="title">{session.title}</span>
    {#if usageLabel}
      <span class="size" title="이 대화의 산출물 용량">{usageLabel}</span>
    {/if}
    <div class="actions">
      <button class="icon-btn" title="이름 변경" onclick={startEdit} aria-label="rename">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
        </svg>
      </button>
      <button class="icon-btn danger" title="삭제" onclick={onDelete} aria-label="delete">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 6h18" />
          <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
          <path d="M19 6 18 20a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
        </svg>
      </button>
    </div>
  {/if}
</div>

<style>
  .row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 10px;
    border-radius: var(--radius-sm);
    cursor: pointer;
    user-select: none;
    color: var(--fg);
    position: relative;
    transition: background var(--dur-fast) ease;
  }

  .row:hover {
    background: var(--bg-hover);
  }

  .row.active {
    background: var(--bg-active);
  }

  .title {
    flex: 1;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font-size: 13.5px;
  }

  .size {
    flex-shrink: 0;
    font-size: 11px;
    color: var(--fg-subtle);
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }

  .actions {
    display: flex;
    gap: 2px;
    /* idle 일 땐 폭을 접어 용량이 우측에 붙고, hover/active 시 버튼이 옆에서 펼쳐진다. */
    max-width: 0;
    overflow: hidden;
    opacity: 0;
    transition: opacity var(--dur-fast) ease, max-width var(--dur-fast) ease;
  }

  .row:hover .actions,
  .row.active .actions {
    max-width: 60px;
    opacity: 1;
  }

  .icon-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    border-radius: var(--radius-sm);
    color: var(--fg-muted);
  }

  .icon-btn:hover {
    background: var(--bg-elevated);
    color: var(--fg);
  }

  .icon-btn.danger:hover {
    color: var(--danger);
    background: var(--danger-bg);
  }

  .edit {
    flex: 1;
    background: var(--bg);
    border: 1px solid var(--accent);
    border-radius: var(--radius-sm);
    padding: 4px 8px;
    outline: none;
    box-shadow: var(--focus-ring);
    font-size: 13.5px;
    min-width: 0;
  }
</style>
