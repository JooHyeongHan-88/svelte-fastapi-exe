<script>
  let { payload } = $props();

  let loadError = $state(false);

  // src 가 바뀌면 에러 상태 초기화
  $effect(() => {
    payload?.src;
    loadError = false;
  });

  function openInNewTab() {
    window.open(payload.src, "_blank", "noopener,noreferrer");
  }
</script>

<div class="artifact-image-wrap">
  <div class="toolbar">
    <span class="img-label">{payload.alt || payload.caption || "이미지"}</span>
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

  {#if loadError}
    <div class="artifact-error">
      <span class="error-icon">🖼️</span>
      <span>이미지를 불러올 수 없습니다.</span>
      <small>{payload.src}</small>
    </div>
  {:else}
    <div class="img-container">
      <img
        src={payload.src}
        alt={payload.alt || ""}
        loading="lazy"
        onerror={() => (loadError = true)}
      />
    </div>
    {#if payload.caption}
      <p class="caption">{payload.caption}</p>
    {/if}
  {/if}
</div>

<style>
  .artifact-image-wrap {
    display: flex;
    flex-direction: column;
    height: 100%;
    gap: 0;
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

  .img-label {
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

  .img-container {
    flex: 1;
    overflow: auto;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 16px;
    min-height: 0;
  }

  img {
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
    border-radius: var(--radius-sm);
    box-shadow: var(--shadow-md);
  }

  .caption {
    font-size: 12px;
    color: var(--fg-muted);
    text-align: center;
    padding: 8px 14px;
    margin: 0;
    flex-shrink: 0;
    border-top: 1px solid var(--border);
  }

  .artifact-error {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 24px;
    margin: 16px;
    border: 2px dashed var(--color-danger, #e53e3e);
    border-radius: var(--radius);
    color: var(--color-danger, #e53e3e);
    font-size: 13px;
    text-align: center;
  }

  .artifact-error .error-icon {
    font-size: 28px;
    filter: grayscale(0.3);
  }

  .artifact-error small {
    font-size: 11px;
    color: var(--fg-muted);
    word-break: break-all;
    max-width: 100%;
  }
</style>
