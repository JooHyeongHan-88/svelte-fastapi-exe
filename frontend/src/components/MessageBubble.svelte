<script>
  import { renderMarkdown } from "../lib/markdown.js";

  let { message } = $props();

  let isUser = $derived(message.role === "user");
  let html = $derived(isUser ? "" : renderMarkdown(message.content));
</script>

<div class="row" class:user={isUser}>
  <div class="bubble" class:user={isUser}>
    {#if isUser}
      <div class="user-content">{message.content}</div>
    {:else}
      {#if !message.content && !message.toolStatus}
        <div class="thinking" aria-label="응답 생성 중">
          <span></span><span></span><span></span>
        </div>
      {:else}
        <div class="markdown">{@html html}</div>
      {/if}
      {#if message.toolStatus}
        <div class="tool-status">{message.toolStatus}</div>
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
