<script>
  import { onMount } from "svelte";
  import { renderMarkdown } from "../lib/markdown.js";

  let { payload } = $props();

  /** @type {"loading"|"ok"|"error"} */
  let status = $state("loading");
  let html = $state("");
  let errorMessage = $state("");

  // payload.src 가 바뀌면 (탭 전환 등) 다시 fetch.
  $effect(() => {
    const src = payload?.src;
    if (!src) {
      status = "error";
      errorMessage = "source 경로가 비어 있습니다.";
      return;
    }
    status = "loading";
    html = "";
    errorMessage = "";

    fetch(src, { cache: "no-cache" })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.text();
      })
      .then((text) => {
        html = renderMarkdown(text);
        status = "ok";
      })
      .catch((err) => {
        errorMessage = String(err?.message ?? err);
        status = "error";
      });
  });

  function openInNewTab() {
    window.open(payload.src, "_blank", "noopener,noreferrer");
  }
</script>

<div class="artifact-md-wrap">
  <div class="toolbar">
    <span class="md-label">{payload?.title || "마크다운 문서"}</span>
    <button class="open-btn" onclick={openInNewTab} title="새 탭에서 열기">
      <svg
        width="14"
        height="14"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        stroke-width="1.8"
      >
        <path d="M6 3H3a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-3" />
        <path d="M10 2h4v4M14 2 8 8" />
      </svg>
      새 탭
    </button>
  </div>

  <div class="md-body">
    {#if status === "loading"}
      <div class="loading">불러오는 중...</div>
    {:else if status === "error"}
      <div class="artifact-error">
        <strong>산출물 파일을 불러올 수 없습니다.</strong>
        <span class="reason">{errorMessage}</span>
      </div>
    {:else}
      <div class="markdown">{@html html}</div>
    {/if}
  </div>
</div>

<style>
  .artifact-md-wrap {
    display: flex;
    flex-direction: column;
    height: 100%;
  }

  .toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 14px;
    border-bottom: 1px solid var(--border);
    background: var(--bg-elevated);
    flex-shrink: 0;
  }

  .md-label {
    font-size: 12px;
    color: var(--fg-muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 70%;
  }

  .open-btn {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 11px;
    font-weight: 500;
    color: var(--accent);
    background: color-mix(in srgb, var(--accent) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent) 25%, transparent);
    border-radius: var(--radius-sm);
    padding: 3px 9px;
    cursor: pointer;
    transition: background 0.15s;
    flex-shrink: 0;
  }

  .open-btn:hover {
    background: color-mix(in srgb, var(--accent) 20%, transparent);
  }

  .md-body {
    flex: 1;
    overflow: auto;
    padding: 16px 20px;
    min-height: 0;
  }

  .loading {
    color: var(--fg-muted);
    font-size: 13px;
    text-align: center;
    padding-top: 32px;
  }

  .artifact-error {
    margin: 24px auto;
    max-width: 360px;
    padding: 14px 16px;
    border: 1px dashed var(--danger, #d33);
    border-radius: var(--radius-md);
    color: var(--danger, #d33);
    background: color-mix(in srgb, var(--danger, #d33) 7%, transparent);
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: 13px;
    text-align: center;
  }

  .artifact-error .reason {
    font-size: 11px;
    opacity: 0.8;
    font-family: var(--font-mono, monospace);
  }

  /* markdown.js 의 출력은 MessageBubble 의 .markdown 스타일과 동일한 톤이어야 한다.
     글로벌 .markdown 셀렉터에 이미 정의가 있으므로 :global 로 덮지 않고 노출만. */
  .markdown :global(h1),
  .markdown :global(h2),
  .markdown :global(h3) {
    margin-top: 1.2em;
  }

  .markdown :global(table) {
    border-collapse: collapse;
    margin: 12px 0;
    font-size: 13px;
  }

  .markdown :global(th),
  .markdown :global(td) {
    border: 1px solid var(--border);
    padding: 6px 10px;
  }

  .markdown :global(th) {
    background: var(--bg-elevated);
    font-weight: 600;
  }

  .markdown :global(pre) {
    background: var(--bg-elevated);
    padding: 10px 12px;
    border-radius: var(--radius-sm);
    overflow-x: auto;
    font-size: 12px;
  }

  .markdown :global(code) {
    font-family: var(--font-mono, monospace);
    font-size: 0.92em;
  }

  .markdown :global(blockquote) {
    border-left: 3px solid var(--border);
    padding-left: 12px;
    margin-left: 0;
    color: var(--fg-muted);
  }
</style>
