<script>
  import { ui } from "../lib/state.svelte.js";
  import {
    closeArtifactPanel,
    openArtifact,
    listSessionArtifacts,
  } from "../lib/artifactActions.svelte.js";
  import {
    saveArtifactWidth,
    ARTIFACT_WIDTH_BOUNDS,
  } from "../lib/storage.js";
  import ArtifactImage from "./ArtifactImage.svelte";
  import ArtifactChart from "./ArtifactChart.svelte";
  import ArtifactMarkdown from "./ArtifactMarkdown.svelte";

  const KIND_ICON = { image: "🖼️", chart: "📊", markdown: "📝" };

  // 활성 세션의 모든 메시지에서 칩을 평탄화 → payload 가 메시지에 영속되어 있으므로
  // 세션 복귀 후에도 동일한 칩 목록을 그대로 복원할 수 있다.
  let sessionArtifacts = $derived(listSessionArtifacts());
  let activeArtifact = $derived(
    sessionArtifacts.find((a) => a.id === ui.activeArtifactId) ?? null,
  );

  // 드래그 리사이즈 — 화면 우측에서 좌측으로 갈수록 너비 증가.
  let resizing = $state(false);

  function clampWidth(px) {
    const upper = Math.min(
      ARTIFACT_WIDTH_BOUNDS.max,
      Math.floor(window.innerWidth * 0.6),
    );
    return Math.min(upper, Math.max(ARTIFACT_WIDTH_BOUNDS.min, Math.round(px)));
  }

  function onHandlePointerDown(e) {
    if (e.button !== 0) return;
    resizing = true;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    e.preventDefault();
  }

  function onHandlePointerMove(e) {
    if (!resizing) return;
    ui.artifactWidth = clampWidth(window.innerWidth - e.clientX);
  }

  function onHandlePointerUp(e) {
    if (!resizing) return;
    resizing = false;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    saveArtifactWidth(ui.artifactWidth);
  }
</script>

{#if ui.artifactPanelOpen}
  <aside
    class="artifact-panel"
    class:resizing
    style="width: {ui.artifactWidth}px"
    aria-label="아티팩트 패널"
  >
    <!-- 좌측 가장자리 드래그 핸들 — 마우스로 패널 너비 조절 -->
    <div
      class="resize-handle"
      role="separator"
      aria-orientation="vertical"
      aria-label="아티팩트 패널 너비 조절"
      onpointerdown={onHandlePointerDown}
      onpointermove={onHandlePointerMove}
      onpointerup={onHandlePointerUp}
      onpointercancel={onHandlePointerUp}
    ></div>
    <!-- 헤더 -->
    <div class="panel-header">
      <span class="panel-title">
        {#if activeArtifact}
          {KIND_ICON[activeArtifact.kind] ?? "📄"}
          {activeArtifact.label}
        {:else}
          아티팩트
        {/if}
      </span>
      <button class="close-btn" onclick={closeArtifactPanel} aria-label="패널 닫기">
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
        >
          <path d="M3 3l10 10M13 3 3 13" />
        </svg>
      </button>
    </div>

    <!-- 아티팩트 탭 목록 (2개 이상일 때만 표시) -->
    {#if sessionArtifacts.length > 1}
      <div class="tab-bar" role="tablist">
        {#each sessionArtifacts as artifact (artifact.id)}
          <button
            class="tab"
            class:active={artifact.id === ui.activeArtifactId}
            role="tab"
            aria-selected={artifact.id === ui.activeArtifactId}
            onclick={() => openArtifact(artifact.id)}
            title={artifact.label}
          >
            {KIND_ICON[artifact.kind] ?? "📄"}
            <span class="tab-label">{artifact.label}</span>
          </button>
        {/each}
      </div>
    {/if}

    <!-- 본문 렌더러 -->
    <div class="panel-body">
      {#if activeArtifact}
        {#if activeArtifact.kind === "image"}
          <ArtifactImage payload={activeArtifact.payload} />
        {:else if activeArtifact.kind === "chart"}
          <ArtifactChart payload={activeArtifact.payload} />
        {:else if activeArtifact.kind === "markdown"}
          <ArtifactMarkdown payload={activeArtifact.payload} />
        {:else}
          <div class="unknown-kind">알 수 없는 아티팩트 유형</div>
        {/if}
      {:else}
        <div class="empty">아티팩트가 없습니다.</div>
      {/if}
    </div>
  </aside>
{/if}

<style>
  .artifact-panel {
    /* width 는 ui.artifactWidth 로 동적 지정. min/max 가드는 JS clampWidth 가 담당. */
    height: 100%;
    display: flex;
    flex-direction: column;
    background: var(--bg);
    border-left: 1px solid var(--border);
    box-shadow: -4px 0 16px rgba(0, 0, 0, 0.06);
    animation: panel-slide-in 0.18s ease-out;
    overflow: hidden;
    flex-shrink: 0;
    position: relative;
  }

  .artifact-panel.resizing {
    user-select: none;
    cursor: ew-resize;
  }

  .resize-handle {
    position: absolute;
    top: 0;
    left: 0;
    width: 6px;
    height: 100%;
    cursor: ew-resize;
    z-index: 10;
    background: transparent;
    transition: background 0.12s;
    touch-action: none;
  }

  .resize-handle:hover,
  .artifact-panel.resizing .resize-handle {
    background: color-mix(in srgb, var(--accent) 35%, transparent);
  }

  @keyframes panel-slide-in {
    from {
      opacity: 0;
      transform: translateX(24px);
    }
    to {
      opacity: 1;
      transform: translateX(0);
    }
  }

  .panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 14px;
    border-bottom: 1px solid var(--border);
    background: var(--bg-elevated);
    flex-shrink: 0;
    min-height: 0;
  }

  .panel-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--fg);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
  }

  .close-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    border: none;
    background: transparent;
    color: var(--fg-muted);
    cursor: pointer;
    border-radius: var(--radius-sm);
    flex-shrink: 0;
    transition: background 0.12s, color 0.12s;
    margin-left: 8px;
  }

  .close-btn:hover {
    background: var(--bg-hover);
    color: var(--fg);
  }

  /* 탭 바 */
  .tab-bar {
    display: flex;
    gap: 2px;
    padding: 4px 8px;
    background: var(--bg-elevated);
    border-bottom: 1px solid var(--border);
    overflow-x: auto;
    flex-shrink: 0;
  }

  .tab {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    padding: 3px 9px;
    border-radius: var(--radius-sm);
    border: 1px solid transparent;
    background: transparent;
    color: var(--fg-muted);
    cursor: pointer;
    white-space: nowrap;
    transition: background 0.12s;
    max-width: 140px;
  }

  .tab:hover {
    background: var(--bg-hover);
  }

  .tab.active {
    background: var(--bg);
    border-color: var(--border);
    color: var(--fg);
    font-weight: 500;
  }

  .tab-label {
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* 본문 */
  .panel-body {
    flex: 1;
    overflow: hidden;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  .empty,
  .unknown-kind {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--fg-muted);
    font-size: 13px;
  }
</style>
