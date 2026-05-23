<script>
  import { ui } from "../lib/state.svelte.js";
  import { sendMessage } from "../lib/chatActions.svelte.js";

  let value = $state("");
  let textareaEl = $state(null);

  const MAX_HEIGHT = 200;

  function autoResize() {
    if (!textareaEl) return;
    textareaEl.style.height = "auto";
    const next = Math.min(textareaEl.scrollHeight, MAX_HEIGHT);
    textareaEl.style.height = next + "px";
  }

  function onInput() {
    autoResize();
  }

  async function submit() {
    const text = value;
    if (!text.trim() || ui.streaming) return;
    value = "";
    autoResize();
    await sendMessage(text);
  }

  function onKey(e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      submit();
    }
  }

  let canSend = $derived(value.trim().length > 0 && !ui.streaming);
</script>

<div class="composer-wrap">
  <div class="composer">
    <textarea
      bind:this={textareaEl}
      bind:value
      oninput={onInput}
      onkeydown={onKey}
      placeholder={ui.streaming ? "응답을 기다리는 중…" : "메시지를 입력하세요"}
      rows="1"
      disabled={ui.streaming}
    ></textarea>
    <button class="send" onclick={submit} disabled={!canSend} aria-label="전송">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M22 2 11 13" />
        <path d="m22 2-7 20-4-9-9-4 20-7z" />
      </svg>
    </button>
  </div>
  <div class="hint">Enter 로 전송 · Shift+Enter 줄바꿈</div>
</div>

<style>
  .composer-wrap {
    max-width: 760px;
    margin: 0 auto;
    padding: 12px 24px 18px;
    width: 100%;
  }

  .composer {
    display: flex;
    align-items: flex-end;
    gap: 8px;
    background: var(--bg-elevated);
    border: 1px solid var(--border-strong);
    border-radius: 14px;
    padding: 10px 10px 10px 14px;
    transition: border-color 0.12s ease, box-shadow 0.12s ease;
  }

  .composer:focus-within {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent);
  }

  textarea {
    flex: 1;
    resize: none;
    border: none;
    outline: none;
    background: transparent;
    font-size: 14.5px;
    line-height: 1.5;
    padding: 4px 0;
    max-height: 200px;
    color: var(--fg);
  }

  textarea::placeholder {
    color: var(--fg-subtle);
  }

  .send {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 34px;
    height: 34px;
    border-radius: 10px;
    background: var(--accent);
    color: var(--accent-fg);
    transition: background 0.12s ease, transform 0.06s ease;
  }

  .send:hover:not(:disabled) {
    background: var(--accent-hover);
  }

  .send:active:not(:disabled) {
    transform: scale(0.96);
  }

  .send:disabled {
    background: var(--border-strong);
    color: var(--fg-subtle);
  }

  .hint {
    text-align: center;
    margin-top: 8px;
    font-size: 11.5px;
    color: var(--fg-subtle);
  }
</style>
