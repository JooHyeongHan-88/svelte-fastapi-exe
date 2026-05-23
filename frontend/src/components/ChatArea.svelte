<script>
  import { ui, activeSession } from "../lib/state.svelte.js";
  import MessageBubble from "./MessageBubble.svelte";
  import { tick } from "svelte";

  let session = $derived(activeSession());
  let messages = $derived(session?.messages ?? []);

  let scrollEl = $state(null);
  let prevLastMessageId = $state(null);

  // 메시지 추가/스트리밍 시 자동 하단 스크롤. 마지막 메시지 id가 바뀌었을 때만 즉시 스크롤.
  $effect(() => {
    const last = messages[messages.length - 1];
    if (!scrollEl || !last) return;

    const isNewMessage = last.id !== prevLastMessageId;
    prevLastMessageId = last.id;

    tick().then(() => {
      if (!scrollEl) return;
      if (isNewMessage) {
        scrollEl.scrollTop = scrollEl.scrollHeight;
      } else {
        // 스트리밍 중에는 사용자가 위로 스크롤했으면 강제 이동 안 함.
        const nearBottom =
          scrollEl.scrollHeight - scrollEl.scrollTop - scrollEl.clientHeight < 120;
        if (nearBottom) scrollEl.scrollTop = scrollEl.scrollHeight;
      }
    });
  });
</script>

<div class="scroll" bind:this={scrollEl}>
  <div class="inner">
    {#if messages.length === 0}
      <div class="empty">
        <h1>무엇을 도와드릴까요?</h1>
        <p>아래 입력창에 메시지를 보내 대화를 시작하세요.</p>
      </div>
    {:else}
      {#each messages as msg (msg.id)}
        <MessageBubble message={msg} />
      {/each}
      <div class="tail-space"></div>
    {/if}
  </div>
</div>

<style>
  .scroll {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
  }

  .inner {
    max-width: 760px;
    margin: 0 auto;
    padding: 24px 24px 0;
  }

  .empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 18vh 0;
  }

  .empty h1 {
    font-size: 28px;
    font-weight: 600;
    color: var(--fg);
    margin: 0 0 8px;
  }

  .empty p {
    color: var(--fg-muted);
    margin: 0;
  }

  .tail-space {
    height: 16px;
  }
</style>
