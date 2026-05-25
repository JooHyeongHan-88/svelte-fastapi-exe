<script>
  import { renderMarkdown } from "../lib/markdown.js";
  import { ui } from "../lib/state.svelte.js";
  import ReasoningBlock from "./ReasoningBlock.svelte";
  import TodoProgress from "./TodoProgress.svelte";
  import SkillCompleteBadge from "./SkillCompleteBadge.svelte";
  import AskUserCard from "./AskUserCard.svelte";
  import { openArtifact } from "../lib/artifactActions.svelte.js";

  const ARTIFACT_ICON = { image: "🖼️", chart: "📊" };

  let { message } = $props();

  let isUser = $derived(message.role === "user");
  let html = $derived(isUser ? "" : renderMarkdown(message.content));
  // 이 메시지가 현재 스트리밍 중인 마지막 assistant 메시지인지 판별한다.
  let isStreaming = $derived(ui.streaming);
</script>

<div class="row" class:user={isUser}>
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
                <div class="skill-bar">
                  {#each slot.activeSkills as skill (skill)}
                    <span class="skill-chip">
                      <span class="skill-icon">✦</span>
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
</div>

<style>
  .row {
    display: flex;
    justify-content: flex-start;
    margin: 18px 0;
  }

  .row.user {
    justify-content: flex-end;
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
