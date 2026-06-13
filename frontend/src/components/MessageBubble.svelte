<script>
  import { renderMarkdown } from "../lib/markdown.js";
  import { ui } from "../lib/state.svelte.js";
  import Segment from "./Segment.svelte";
  import ReasoningBlock from "./ReasoningBlock.svelte";
  import TodoProgress from "./TodoProgress.svelte";
  import SkillCompleteBadge from "./SkillCompleteBadge.svelte";
  import AskUserCard from "./AskUserCard.svelte";
  import {
    openArtifact,
    artifactRefPath,
    insertArtifactReference,
  } from "../lib/artifactActions.svelte.js";
  import { rewindToMessage } from "../lib/chatActions.svelte.js";
  import { formatAbsoluteTime, formatDuration } from "../lib/format.js";
  import TurnStatus from "./TurnStatus.svelte";
  import ArtifactIcon from "./ArtifactIcon.svelte";

  let { message } = $props();

  let isUser = $derived(message.role === "user");
  // 구 메시지(segments 없음) 전용 마크다운 렌더링
  let legacyHtml = $derived(isUser ? "" : renderMarkdown(message.content ?? ""));
  // isStreaming: Segment 컴포넌트에 전달하기 위해 전역 ui.streaming 유지
  let isStreaming = $derived(ui.streaming);

  // 신규 메시지 여부: assistantMsg 가 segments: [] 로 초기화되므로 Array 이면 새 형식.
  // undefined/null 이면 localStorage 에서 복원된 구 메시지 → legacy fallback.
  let isNewStyle = $derived(Array.isArray(message.segments));

  // 신규 segments 타임라인 사용 여부
  let hasSegments = $derived(isNewStyle && message.segments.length > 0);

  // per-message 생성 중 여부 (TurnStatus 에 사용; thinking dots 대체)
  let isThisMsgStreaming = $derived(!!message.streaming);

  // 완료 표식: 신규 형식 assistant 메시지이고 생성이 끝난 경우
  let showDoneMarker = $derived(
    !isUser && isNewStyle && !isThisMsgStreaming && !message.isStopped,
  );

  // legacy 표시 — 구 메시지 (segments 필드 없음)
  let showLegacy = $derived(!isNewStyle);

  function onRewindClick() {
    if (ui.streaming) return;
    const ok = window.confirm(
      "이 메시지 시점으로 대화를 되돌릴까요?\n이후 대화는 삭제되고, 이 메시지가 입력창에 다시 채워집니다.",
    );
    if (ok) rewindToMessage(message.id);
  }
</script>

<div class="row" class:user={isUser}>
  <div class="bubble-wrap">
  <div class="bubble" class:user={isUser}>
    {#if isUser}
      <!-- 슬래시 커맨드로 부착한 skill 을 대화창 안에서도 표시 -->
      {#if message.appliedSkills && message.appliedSkills.length > 0}
        <div class="skill-bar user-skills">
          {#each message.appliedSkills as skill (skill)}
            <span class="skill-chip user-chip">
              <span class="skill-icon">✦</span>
              {skill}
            </span>
          {/each}
        </div>
      {/if}
      <!-- 인용 pill 을 본문 텍스트 흐름 안에 인라인으로 렌더 (parts 우선) -->
      {#if message.parts && message.parts.length > 0}
        <div class="user-content">{#each message.parts as part, i (i)}{#if part.type === "ref"}<span class="ref-pill" title={part.path}><ArtifactIcon kind="file" size={12} /><span class="ref-pill-label">{part.label}</span></span>{:else}{part.value}{/if}{/each}</div>
      {:else if message.refs && message.refs.length > 0}
        <!-- (구) refs 폴백 — 트레이형 pill + 본문 -->
        <div class="ref-pill-bar">
          {#each message.refs as ref (ref.path)}
            <span class="ref-pill" title={ref.path}>
              <ArtifactIcon kind="file" size={12} />
              <span class="ref-pill-label">{ref.label}</span>
            </span>
          {/each}
        </div>
        {#if message.content}
          <div class="user-content">{message.content}</div>
        {/if}
      {:else if message.content}
        <div class="user-content">{message.content}</div>
      {/if}

    {:else}
      <!-- ── 완료 표식 (정적) — 생성이 끝난 신규 형식 메시지에만 표시 ── -->
      {#if showDoneMarker}
        <div class="done-marker" aria-label="응답 완료" title="응답 완료"></div>
      {/if}

      <!-- ── 활성 스킬 뱃지 (message 레벨, 상단 고정) ── -->
      {#if message.activeSkills && message.activeSkills.length > 0}
        <div class="skill-bar">
          {#each message.activeSkills as skill (skill)}
            <span class="skill-chip">
              <span class="skill-icon">✦</span>
              {skill}
            </span>
          {/each}
        </div>
      {/if}

      <!-- ══ 신규: 시간순 Collapsible 타임라인 ══ -->
      {#if hasSegments}
        {#each message.segments as seg (seg.id)}
          <Segment {seg} {isStreaming} />
        {/each}
      {/if}

      <!-- ── TurnStatus — 생성 중 내내 표시 (세그먼트 유무 무관) ── -->
      {#if isThisMsgStreaming}
        <TurnStatus {message} />
      {/if}

      <!-- ══ legacy fallback — segments 없는 구 메시지 ══ -->
      {#if showLegacy}
        {#if message.reasoning}
          <ReasoningBlock
            text={message.reasoning}
            streaming={false}
          />
        {/if}
        {#if message.todos && message.todos.length > 0}
          <TodoProgress todos={message.todos} complete={message.skillComplete ?? null} />
        {:else if message.skillComplete}
          <SkillCompleteBadge data={message.skillComplete} />
        {/if}
        <!-- 구 agentProgress — legacy 렌더 (간략화, 접힘 없음) -->
        {#if message.agentProgress && message.agentProgress.length > 0}
          {#each message.agentProgress as slot, idx (idx)}
            {#if slot.deltas || slot.toolStatus || (slot.todos && slot.todos.length > 0)}
              <div class="legacy-agent">
                <div class="legacy-agent-label">{slot.agentId}</div>
                {#if slot.todos && slot.todos.length > 0}
                  <TodoProgress todos={slot.todos} complete={slot.skillComplete ?? null} />
                {/if}
                {#if slot.toolStatus}
                  <div class="legacy-tool-status">{slot.toolStatus}</div>
                {/if}
                {#if slot.deltas}
                  <div class="legacy-agent-text">{slot.deltas}</div>
                {/if}
              </div>
            {/if}
          {/each}
        {/if}
        {#if message.content}
          <div class="markdown" class:fallback={message.isFallback}>{@html legacyHtml}</div>
        {/if}
        {#if message.toolStatus}
          <div class="tool-status">{message.toolStatus}</div>
        {/if}
      {/if}

      <!-- ── AskUserCard — 항상 타임라인 뒤 ── -->
      {#if message.askUser}
        <AskUserCard askUser={message.askUser} />
      {/if}

      <!-- ── ESC 중지 표시 ── -->
      {#if message.isStopped}
        <div class="stopped-footer" role="status">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <rect x="6" y="6" width="12" height="12" rx="2" />
          </svg>
          응답이 중지되었습니다
        </div>
      {/if}

      <!-- ── 아티팩트 칩 ── -->
      {#if message.artifactChips && message.artifactChips.length > 0}
        <div class="artifact-chip-bar">
          {#each message.artifactChips as chip (chip.id)}
            <div class="artifact-chip-group">
              <button
                class="artifact-chip"
                onclick={() => openArtifact(chip.id)}
                title={chip.label}
              >
                <ArtifactIcon kind={chip.kind} size={13} />
                <span class="artifact-chip-label">{chip.label}</span>
                <svg
                  class="artifact-chip-arrow"
                  width="11"
                  height="11"
                  viewBox="0 0 11 11"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.8"
                >
                  <path d="M2 5.5h7M6 2.5l3 3-3 3" />
                </svg>
              </button>
              {#if artifactRefPath(chip)}
                <button
                  class="artifact-chip-ref"
                  title="이 산출물 경로를 입력창에 삽입"
                  aria-label="입력창에 참조 삽입"
                  onclick={(e) => {
                    e.stopPropagation();
                    insertArtifactReference(chip.id);
                  }}
                >
                  @
                </button>
              {/if}
            </div>
          {/each}
        </div>
      {/if}
    {/if}
  </div>

  <!-- hover 시 나타나는 메타 footer -->
  <div class="msg-footer">
    <span class="msg-time">{formatAbsoluteTime(message.createdAt)}</span>
    {#if !isUser && message.durationMs != null}
      <span class="msg-duration">{formatDuration(message.durationMs)}</span>
    {/if}
    {#if isUser}
      <button
        type="button"
        class="rewind-btn"
        onclick={onRewindClick}
        disabled={ui.streaming}
        aria-label="이 시점으로 대화 되돌리기"
        title="이 시점으로 대화 되돌리기"
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <polyline points="1 4 1 10 7 10" />
          <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" />
        </svg>
      </button>
    {/if}
  </div>
  </div>
</div>

<style>
  .row {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    margin: 18px 0;
  }

  .row.user {
    align-items: flex-end;
  }

  .bubble-wrap {
    display: flex;
    flex-direction: column;
    max-width: 100%;
  }

  .row.user .bubble-wrap {
    max-width: 78%;
    align-items: flex-end;
  }

  .bubble {
    max-width: 100%;
  }

  .bubble.user {
    max-width: 100%;
    background: var(--user-bubble);
    color: var(--fg);
    padding: 10px 14px;
    border-radius: var(--radius-lg) var(--radius-lg) var(--radius-sm) var(--radius-lg);
  }

  .user-content {
    white-space: pre-wrap;
    word-wrap: break-word;
    font-size: 15px; /* 채팅 본문(.markdown 15px)과 톤 일치 */
    line-height: 1.6;
  }

  /* ── 산출물 인용 pill — 본문과 구분되는 액센트 톤 (입력창 pill 과 시각 일관) ── */
  .ref-pill-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 6px;
  }

  .ref-pill {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    max-width: 240px;
    vertical-align: baseline;
    font-size: 13px;
    font-weight: 500;
    color: var(--accent);
    background: var(--accent-soft);
    border: 1px solid var(--accent-border);
    border-radius: var(--radius-sm);
    padding: 0 6px;
    margin: 0 1px;
    line-height: 1.5;
  }

  .ref-pill-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* ── 스킬 뱃지 바 ── */
  .skill-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 10px;
  }

  .user-skills {
    margin-bottom: 6px;
  }

  .user-chip {
    color: var(--accent);
    background: var(--accent-soft-strong);
    border-color: var(--accent-border);
  }

  .skill-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    font-weight: 500;
    color: var(--accent);
    background: var(--accent-soft);
    border: 1px solid var(--accent-border);
    border-radius: var(--radius-full);
    padding: 2px 9px 2px 7px;
    line-height: 1.6;
    white-space: nowrap;
    animation: skill-pop var(--dur-slow) ease-out both;
  }

  .skill-icon {
    font-size: 12px;
    line-height: 1;
  }

  @keyframes skill-pop {
    from { opacity: 0; transform: scale(0.85) translateY(-2px); }
    to   { opacity: 1; transform: scale(1) translateY(0); }
  }

  /* ── 아티팩트 칩 ── */
  .artifact-chip-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 10px;
  }

  .artifact-chip-group {
    display: inline-flex;
    align-items: stretch;
  }

  .artifact-chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 12px;
    font-weight: 500;
    color: var(--accent);
    background: var(--accent-soft);
    border: 1px solid var(--accent-border);
    border-radius: var(--radius-sm);
    padding: 4px 10px 4px 8px;
    cursor: pointer;
    transition: background var(--dur-fast);
    white-space: nowrap;
    max-width: 220px;
  }

  .artifact-chip:hover {
    background: var(--accent-soft-strong);
  }

  /* 참조 삽입 보조 버튼 — 메인 칩과 붙은 작은 '@' 버튼 */
  .artifact-chip-group:has(.artifact-chip-ref) .artifact-chip {
    border-top-right-radius: 0;
    border-bottom-right-radius: 0;
  }

  .artifact-chip-ref {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    font-size: 13px;
    font-weight: 700;
    color: var(--accent);
    background: var(--accent-soft);
    border: 1px solid var(--accent-border);
    border-left: none;
    border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
    cursor: pointer;
    transition: background var(--dur-fast);
  }

  .artifact-chip-ref:hover {
    background: var(--accent-soft-strong);
  }

  .artifact-chip-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
  }

  .artifact-chip-arrow {
    flex-shrink: 0;
    opacity: 0.7;
  }

  /* ── 중지 footer ── */
  .stopped-footer {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    margin-top: 8px;
    font-size: 11.5px;
    color: var(--fg-subtle);
  }

  /* ── hover 메타 footer ── */
  .msg-footer {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 4px;
    font-size: 11px;
    color: var(--fg-subtle);
    opacity: 0;
    transition: opacity var(--dur-fast) ease;
    pointer-events: none;
  }

  .row:hover .msg-footer,
  .msg-footer:focus-within {
    opacity: 1;
    pointer-events: auto;
  }

  .row.user .msg-footer {
    justify-content: flex-end;
  }

  .rewind-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    border-radius: var(--radius-sm);
    color: var(--fg-subtle);
    background: transparent;
    cursor: pointer;
    transition: background var(--dur-fast), color var(--dur-fast);
  }

  .rewind-btn:hover:not(:disabled) {
    background: var(--bg-hover);
    color: var(--fg);
  }

  .rewind-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  /* ── 완료 정적 표식 ── */
  .done-marker {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--fg-subtle, var(--fg-muted));
    opacity: 0.45;
    margin-bottom: 8px;
    flex-shrink: 0;
  }

  /* ── hover footer 소요시간 ── */
  .msg-duration {
    font-variant-numeric: tabular-nums;
  }

  /* ── legacy fallback 전용 스타일 ── */
  .markdown {
    /* marked + hljs 인라인 스타일 수용 */
  }

  .markdown.fallback {
    background-color: color-mix(in srgb, var(--danger) 5%, transparent);
    border: 1px dashed var(--danger);
    padding: 12px;
    border-radius: var(--radius-sm);
    margin-top: 8px;
  }

  .tool-status {
    margin-top: 8px;
    font-size: 12px;
    color: var(--fg-muted);
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    padding: 5px 10px;
    border-radius: var(--radius-sm);
    display: inline-block;
    font-family: var(--font-mono);
  }

  .legacy-agent {
    margin: 6px 0 10px 12px;
    padding: 8px 12px;
    border-left: 2px solid var(--border);
    background: var(--bg-elevated);
    border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
    font-size: 12px;
    color: var(--fg-muted);
  }

  .legacy-agent-label {
    font-weight: 600;
    font-size: 11px;
    margin-bottom: 4px;
    color: var(--accent);
  }

  .legacy-tool-status {
    font-family: var(--font-mono);
    font-size: 11px;
    margin-bottom: 4px;
  }

  .legacy-agent-text {
    white-space: pre-wrap;
    word-wrap: break-word;
    line-height: 1.5;
  }
</style>
