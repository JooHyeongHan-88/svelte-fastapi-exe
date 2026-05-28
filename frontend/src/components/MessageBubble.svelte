<script>
  import { renderMarkdown } from "../lib/markdown.js";
  import { ui } from "../lib/state.svelte.js";
  import ReasoningBlock from "./ReasoningBlock.svelte";
  import TodoProgress from "./TodoProgress.svelte";
  import SkillCompleteBadge from "./SkillCompleteBadge.svelte";
  import AskUserCard from "./AskUserCard.svelte";
  import { openArtifact } from "../lib/artifactActions.svelte.js";
  import { rewindToMessage } from "../lib/chatActions.svelte.js";
  import { formatAbsoluteTime } from "../lib/format.js";

  const ARTIFACT_ICON = { image: "🖼️", chart: "📊" };

  let { message } = $props();

  let isUser = $derived(message.role === "user");
  let html = $derived(isUser ? "" : renderMarkdown(message.content));
  // 이 메시지가 현재 스트리밍 중인 마지막 assistant 메시지인지 판별한다.
  let isStreaming = $derived(ui.streaming);

  function onRewindClick() {
    if (ui.streaming) return;
    // 네이티브 confirm 으로 단순화 — 세션 삭제 (SessionItem) 와 동일한 패턴.
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
      {#if message.content}
        <div class="user-content">{message.content}</div>
      {/if}
    {:else}
      <!-- 활성 스킬 뱃지 — skill_active 이벤트 수신 시 표시 -->
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

      <!-- 멀티 에이전트 위임 trail — AgentSwitch/Return 이벤트 누적 -->
      {#if message.agentTrail && message.agentTrail.length > 0}
        <div class="agent-trail">
          {#each message.agentTrail as hop, idx (idx)}
            <span class="agent-chip" class:returned={hop.summary != null}>
              <span class="agent-arrow">{hop.summary != null ? "✓" : "🔄"}</span>
              {hop.from} → {hop.to}
            </span>
          {/each}
        </div>
      {/if}

      <!-- 서브 에이전트 진행 영역 — AgentProgress 의 inner delta/tool/todo/skill/reasoning 표시 -->
      {#if message.agentProgress && message.agentProgress.length > 0}
        {#each message.agentProgress as slot, idx (idx)}
          {#if slot.deltas || slot.toolStatus || (slot.todos && slot.todos.length > 0) || (slot.activeSkills && slot.activeSkills.length > 0) || slot.reasoning}
            <div class="agent-progress">
              <div class="agent-progress-label">{slot.agentId}</div>
              {#if slot.activeSkills && slot.activeSkills.length > 0}
                <div class="agent-skill-bar">
                  {#each slot.activeSkills as skill (skill)}
                    <span class="agent-skill-chip">
                      <span class="agent-skill-icon">◆</span>
                      {skill}
                    </span>
                  {/each}
                </div>
              {/if}
              {#if slot.reasoning}
                <ReasoningBlock
                  text={slot.reasoning}
                  streaming={isStreaming && !slot.deltas}
                />
              {/if}
              {#if slot.toolStatus}
                <div class="agent-progress-tool">{slot.toolStatus}</div>
              {/if}
              {#if slot.todos && slot.todos.length > 0}
                <TodoProgress todos={slot.todos} toolStatus={slot.toolStatus} />
              {/if}
              {#if slot.skillComplete}
                <SkillCompleteBadge data={slot.skillComplete} />
              {/if}
              {#if slot.deltas}
                <div class="agent-progress-text">{slot.deltas}</div>
              {/if}
            </div>
          {/if}
        {/each}
      {/if}

      <!-- 추론 과정 블록 — ReasoningEvent 수신 시 표시 -->
      {#if message.reasoning}
        <ReasoningBlock
          text={message.reasoning}
          streaming={isStreaming && !message.content}
        />
      {/if}

      <!-- 작업 진행 체크리스트 — TodoUpdateEvent 수신 시 표시 -->
      {#if message.todos && message.todos.length > 0}
        <TodoProgress todos={message.todos} toolStatus={message.toolStatus} />
      {/if}

      <!-- 전체 작업 완료 배지 — SkillCompleteEvent 수신 시 표시 -->
      {#if message.skillComplete}
        <SkillCompleteBadge data={message.skillComplete} />
      {/if}

      {#if !message.content && !message.toolStatus && !message.reasoning && !(message.todos && message.todos.length > 0)}
        <div class="thinking" aria-label="응답 생성 중">
          <span></span><span></span><span></span>
        </div>
      {:else if message.content}
        <div class="markdown" class:fallback={message.isFallback}>{@html html}</div>
      {/if}
      {#if message.toolStatus}
        <div class="tool-status">{message.toolStatus}</div>
      {/if}

      <!-- 슬롯 질문 카드 — AskUserEvent 수신 시 표시 -->
      {#if message.askUser}
        <AskUserCard askUser={message.askUser} />
      {/if}

      <!-- ESC 로 중지된 응답 표시 — stopStreaming() 이 isStopped 플래그를 단다. -->
      {#if message.isStopped}
        <div class="stopped-footer" role="status">⏹ 응답이 중지되었습니다</div>
      {/if}

      <!-- 아티팩트 칩 — display_image / display_chart 결과 -->
      {#if message.artifactChips && message.artifactChips.length > 0}
        <div class="artifact-chip-bar">
          {#each message.artifactChips as chip (chip.id)}
            <button
              class="artifact-chip"
              onclick={() => openArtifact(chip.id)}
              title={chip.label}
            >
              {ARTIFACT_ICON[chip.kind] ?? "📄"}
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
          {/each}
        </div>
      {/if}
    {/if}
  </div>

  <!-- hover 시 나타나는 메타 footer — 작성 시간 + (user 메시지에만) rewind 버튼 -->
  <div class="msg-footer">
    <span class="msg-time">{formatAbsoluteTime(message.createdAt)}</span>
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
    /* bubble + footer 를 세로로 쌓고, user 는 우측, assistant 는 좌측에 정렬한다. */
    flex-direction: column;
    align-items: flex-start;
    margin: 18px 0;
  }

  .row.user {
    align-items: flex-end;
  }

  /* bubble-wrap 은 bubble 과 footer 가 같은 너비 트랙에서 정렬을 공유하기 위한 컨테이너.
     bubble.user 의 max-width 78% 와 동일한 제약을 부모에서 걸어 footer 가 bubble 너비 안에 머문다. */
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
    max-width: 78%;
    background: var(--user-bubble);
    color: var(--fg);
    padding: 10px 14px;
    border-radius: 16px 16px 4px 16px;
  }

  .user-content {
    white-space: pre-wrap;
    word-wrap: break-word;
    font-size: 14px;
    line-height: 1.6;
  }

  .markdown.fallback {
    background-color: color-mix(in srgb, var(--danger) 5%, transparent);
    border: 1px dashed var(--danger);
    padding: 12px;
    border-radius: 8px;
    margin-top: 8px;
  }

  /* ── 스킬 뱃지 바 ── */
  .skill-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 10px;
  }

  /* 사용자 버블 안 skill bar — 콘텐츠 위에 표시 */
  .user-skills {
    margin-bottom: 6px;
  }

  /* 사용자 버블 안 chip — accent 대신 반투명 흰색 계열로 대비 확보 */
  .user-chip {
    color: var(--accent);
    background: color-mix(in srgb, var(--accent) 15%, transparent);
    border-color: color-mix(in srgb, var(--accent) 35%, transparent);
  }

  .skill-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    font-weight: 500;
    color: var(--accent);
    background: color-mix(in srgb, var(--accent) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent) 25%, transparent);
    border-radius: 20px;
    padding: 2px 9px 2px 7px;
    line-height: 1.6;
    white-space: nowrap;
    animation: skill-pop 0.18s ease-out both;
  }

  .skill-icon {
    font-size: 12px;
    line-height: 1;
  }

  @keyframes skill-pop {
    from {
      opacity: 0;
      transform: scale(0.85) translateY(-2px);
    }
    to {
      opacity: 1;
      transform: scale(1) translateY(0);
    }
  }

  /* ── 에이전트 내부 스킬 뱃지 (skill-chip 과 구분) ── */
  .agent-skill-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
    margin-bottom: 8px;
  }

  .agent-skill-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 10px;
    font-weight: 600;
    color: var(--fg-muted);
    background: color-mix(in srgb, var(--border) 40%, transparent);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 2px 7px 2px 6px;
    line-height: 1.6;
    white-space: nowrap;
    letter-spacing: 0.02em;
    animation: skill-pop 0.18s ease-out both;
  }

  .agent-skill-icon {
    font-size: 8px;
    line-height: 1;
    opacity: 0.65;
  }

  /* ── 멀티 에이전트 trail / progress ── */
  .agent-trail {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 10px;
  }

  .agent-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    font-weight: 500;
    color: var(--fg-muted);
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 2px 9px 2px 7px;
    line-height: 1.6;
    white-space: nowrap;
    animation: skill-pop 0.18s ease-out both;
  }

  .agent-chip.returned {
    color: var(--accent);
    background: color-mix(in srgb, var(--accent) 10%, transparent);
    border-color: color-mix(in srgb, var(--accent) 30%, transparent);
  }

  .agent-arrow {
    font-size: 11px;
    line-height: 1;
  }

  .agent-progress {
    margin: 6px 0 10px 12px;
    padding: 8px 12px;
    border-left: 2px solid var(--border);
    background: var(--bg-elevated);
    border-radius: 0 6px 6px 0;
    font-size: 12px;
    color: var(--fg-muted);
  }

  .agent-progress-label {
    font-weight: 600;
    font-size: 11px;
    margin-bottom: 4px;
    color: var(--accent);
  }

  .agent-progress-tool {
    font-family: var(--font-mono);
    font-size: 11px;
    margin-bottom: 4px;
  }

  .agent-progress-text {
    white-space: pre-wrap;
    word-wrap: break-word;
    line-height: 1.5;
  }

  /* ── 아티팩트 칩 ── */
  .artifact-chip-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 10px;
  }

  .artifact-chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 12px;
    font-weight: 500;
    color: var(--accent);
    background: color-mix(in srgb, var(--accent) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent) 28%, transparent);
    border-radius: var(--radius-sm);
    padding: 4px 10px 4px 8px;
    cursor: pointer;
    transition: background 0.13s;
    white-space: nowrap;
    max-width: 220px;
  }

  .artifact-chip:hover {
    background: color-mix(in srgb, var(--accent) 16%, transparent);
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
    margin-top: 8px;
    font-size: 11.5px;
    color: var(--fg-subtle);
  }

  /* ── hover 메타 footer (시간 + rewind 버튼) ── */
  .msg-footer {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 4px;
    font-size: 11px;
    color: var(--fg-subtle);
    opacity: 0;
    transition: opacity 0.12s ease;
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
    border-radius: 4px;
    color: var(--fg-subtle);
    background: transparent;
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
  }

  .rewind-btn:hover:not(:disabled) {
    background: var(--bg-hover);
    color: var(--fg);
  }

  .rewind-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  /* ── 도구 상태 ── */
  .tool-status {
    margin-top: 8px;
    font-size: 12px;
    color: var(--fg-muted);
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    padding: 5px 10px;
    border-radius: 6px;
    display: inline-block;
    font-family: var(--font-mono);
  }

  .thinking {
    display: inline-flex;
    gap: 4px;
    padding: 6px 0;
  }

  .thinking span {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--fg-muted);
    animation: blink 1.2s infinite ease-in-out both;
  }

  .thinking span:nth-child(2) {
    animation-delay: 0.15s;
  }

  .thinking span:nth-child(3) {
    animation-delay: 0.3s;
  }

  @keyframes blink {
    0%,
    80%,
    100% {
      opacity: 0.25;
      transform: scale(0.85);
    }
    40% {
      opacity: 1;
      transform: scale(1);
    }
  }
</style>
