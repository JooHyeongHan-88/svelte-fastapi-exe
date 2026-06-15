<script>
  // 확장(extension) SPA 를 우측 패널에 iframe 으로 임베드한다. evaluator 처럼 격리된
  // 빌드 SPA 를 그대로 재사용하므로 same-origin iframe 이 유일하게 합리적인 임베드
  // 방식이다 — base="/ext/<tool>/" 라 iframe 안의 에셋·/api/ext 호출이 same-origin 으로
  // 동작하고 Origin 가드도 통과한다. sandbox 는 지정하지 않는다(같은 출처 XHR 필요).
  let { payload } = $props();

  function openInNewTab() {
    if (payload?.src) window.open(payload.src, "_blank", "noopener,noreferrer");
  }
</script>

<div class="artifact-ext-wrap">
  <div class="toolbar">
    <span class="ext-label">{payload?.title || payload?.tool || "확장 도구"}</span>
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

  <div class="ext-body">
    {#if payload?.src}
      <iframe
        class="ext-frame"
        src={payload.src}
        title={payload?.title || payload?.tool || "확장 도구"}
      ></iframe>
    {:else}
      <div class="artifact-error">
        <strong>확장을 불러올 수 없습니다.</strong>
        <span class="reason">src 경로가 비어 있습니다.</span>
      </div>
    {/if}
  </div>
</div>

<style>
  .artifact-ext-wrap {
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

  .ext-label {
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
    background: var(--accent-soft);
    border: 1px solid var(--accent-border);
    border-radius: var(--radius-sm);
    padding: 3px 9px;
    cursor: pointer;
    transition: background var(--dur-fast);
    flex-shrink: 0;
  }

  .open-btn:hover {
    background: var(--accent-soft-strong);
  }

  .ext-body {
    flex: 1;
    min-height: 0;
    display: flex;
  }

  .ext-frame {
    flex: 1;
    width: 100%;
    height: 100%;
    border: 0;
    background: var(--bg);
  }

  .artifact-error {
    margin: 24px auto;
    max-width: 360px;
    padding: 14px 16px;
    border: 1px dashed var(--danger);
    border-radius: var(--radius-md);
    color: var(--danger);
    background: color-mix(in srgb, var(--danger) 7%, transparent);
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
</style>
