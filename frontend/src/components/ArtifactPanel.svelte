<script>
  import { ui } from "../lib/state.svelte.js";
  import { closeArtifactPanel, openArtifact } from "../lib/artifactActions.svelte.js";
  import ArtifactImage from "./ArtifactImage.svelte";
  import ArtifactChart from "./ArtifactChart.svelte";

  const KIND_ICON = { image: "🖼️", chart: "📊" };

  let activeArtifact = $derived(
    ui.artifacts.find((a) => a.id === ui.activeArtifactId) ?? null,
  );
</script>

{#if ui.artifactPanelOpen}
  <aside class="artifact-panel" aria-label="아티팩트 패널">
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
    {#if ui.artifacts.length > 1}
      <div class="tab-bar" role="tablist">
        {#each ui.artifacts as artifact (artifact.id)}
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
    width: 420px;
    min-width: 320px;
    max-width: 50vw;
    height: 100%;
    display: flex;
    flex-direction: column;
    background: var(--bg);
    border-left: 1px solid var(--border);
    box-shadow: -4px 0 16px rgba(0, 0, 0, 0.06);
    animation: panel-slide-in 0.18s ease-out;
    overflow: hidden;
    flex-shrink: 0;
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
