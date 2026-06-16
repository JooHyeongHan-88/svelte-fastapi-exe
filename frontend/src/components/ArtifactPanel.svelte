<script>
  import { onDestroy } from "svelte";
  import { ui } from "../lib/state.svelte.js";
  import {
    closeArtifactPanel,
    toggleArtifactMaximize,
    openArtifact,
    listSessionArtifacts,
    artifactRefPath,
    insertArtifactReference,
    revealArtifactFolder,
    closeExtensionView,
  } from "../lib/artifactActions.svelte.js";
  import {
    saveArtifactWidth,
    ARTIFACT_WIDTH_BOUNDS,
  } from "../lib/storage.js";
  import ArtifactImage from "./ArtifactImage.svelte";
  import ArtifactChart from "./ArtifactChart.svelte";
  import ArtifactMarkdown from "./ArtifactMarkdown.svelte";
  import ArtifactData from "./ArtifactData.svelte";
  import ArtifactExtension from "./ArtifactExtension.svelte";
  import ArtifactIcon from "./ArtifactIcon.svelte";

  // 활성 세션의 모든 메시지에서 칩을 평탄화 → payload 가 메시지에 영속되어 있으므로
  // 세션 복귀 후에도 동일한 칩 목록을 그대로 복원할 수 있다. 드롭다운 런처로 연
  // 휘발 확장 뷰(ui.extensionView)는 대화 산출물이 아니므로 앞에 끼워 함께 보여준다.
  let displayArtifacts = $derived(
    ui.extensionView
      ? [ui.extensionView, ...listSessionArtifacts()]
      : listSessionArtifacts(),
  );
  let activeArtifact = $derived(
    displayArtifacts.find((a) => a.id === ui.activeArtifactId) ?? null,
  );

  // 폴더 열기 실패 피드백 — 탐색기 창은 브라우저 밖에서 열리므로 실패가 조용하면
  // '뒤에 열렸나'와 '실패했나'를 구분할 수 없다. 버튼을 잠시 적색으로 플래시한다.
  const REVEAL_FAILED_FLASH_MS = 2400;
  let revealFailed = $state(false);
  let revealFailedTimer = null;

  async function handleRevealClick() {
    const ok = await revealArtifactFolder(activeArtifact.id);
    if (ok) return;
    revealFailed = true;
    clearTimeout(revealFailedTimer);
    revealFailedTimer = setTimeout(
      () => (revealFailed = false),
      REVEAL_FAILED_FLASH_MS,
    );
  }

  onDestroy(() => clearTimeout(revealFailedTimer));

  // 최대화 뷰의 떠 있는 복귀 버튼 — 평소엔 옅게(idle), hover 시 또렷하게. 최대화 진입
  // 직후 잠시 또렷하게 띄워 발견성을 준다(Chrome F11 의 상단 hint 와 유사). 본문이
  // iframe(확장)일 수 있어 부모가 마우스 위치를 알 수 없으므로, 화면을 가리는 hover
  // 영역 대신 작은 버튼 자체만 항상 클릭 가능하게 둔다(idle 투명도로 hover 느낌 전달).
  const RESTORE_HINT_MS = 2500;
  let restoreHint = $state(false);
  let restoreHintTimer = null;

  $effect(() => {
    clearTimeout(restoreHintTimer);
    if (ui.artifactMaximized) {
      restoreHint = true;
      restoreHintTimer = setTimeout(() => (restoreHint = false), RESTORE_HINT_MS);
    } else {
      restoreHint = false;
    }
  });

  onDestroy(() => clearTimeout(restoreHintTimer));

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
    class:maximized={ui.artifactMaximized}
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
          <ArtifactIcon kind={activeArtifact.kind} size={14} />
          <span class="panel-title-text">{activeArtifact.label}</span>
        {:else}
          아티팩트
        {/if}
      </span>
      <div class="panel-header-actions">
        {#if activeArtifact && artifactRefPath(activeArtifact)}
          <button
            class="ref-btn"
            onclick={() => insertArtifactReference(activeArtifact.id)}
            title="이 산출물 경로를 입력창에 삽입"
            aria-label="입력창에 참조 삽입"
          >
            @ 참조
          </button>
          <button
            class="folder-btn"
            class:failed={revealFailed}
            onclick={handleRevealClick}
            title={revealFailed
              ? "폴더를 열 수 없습니다 — 산출물이 삭제되었을 수 있습니다"
              : "산출물 폴더를 탐색기에서 열기"}
            aria-label="산출물 폴더를 탐색기에서 열기"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              stroke-width="1.4"
              stroke-linejoin="round"
            >
              <path d="M1.75 4.25a1 1 0 0 1 1-1h2.7l1.4 1.5h6.4a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H2.75a1 1 0 0 1-1-1z" />
            </svg>
          </button>
        {/if}
        <button
          class="maximize-btn"
          onclick={toggleArtifactMaximize}
          title="최대화 (본문을 화면 전체로)"
          aria-label="패널 최대화"
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.6"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M6 2H2v4M14 6V2h-4M10 14h4v-4M2 10v4h4" />
          </svg>
        </button>
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
    </div>

    <!-- 아티팩트 탭 목록 (2개 이상일 때만 표시) -->
    {#if displayArtifacts.length > 1}
      <div class="tab-bar" role="tablist">
        {#each displayArtifacts as artifact (artifact.id)}
          <button
            class="tab"
            class:active={artifact.id === ui.activeArtifactId}
            role="tab"
            aria-selected={artifact.id === ui.activeArtifactId}
            onclick={() => openArtifact(artifact.id)}
            title={artifact.label}
          >
            <ArtifactIcon kind={artifact.kind} size={12} />
            <span class="tab-label">{artifact.label}</span>
            {#if ui.extensionView && artifact.id === ui.extensionView.id}
              <!-- 휘발 확장 뷰는 닫기(×) 가능 — 메시지 칩은 영향 없음. -->
              <span
                class="tab-close"
                role="button"
                tabindex="0"
                aria-label="확장 닫기"
                title="확장 닫기"
                onclick={(e) => {
                  e.stopPropagation();
                  closeExtensionView();
                }}
                onkeydown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    e.stopPropagation();
                    closeExtensionView();
                  }
                }}
              >×</span>
            {/if}
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
        {:else if activeArtifact.kind === "data"}
          <ArtifactData payload={activeArtifact.payload} />
        {:else if activeArtifact.kind === "extension"}
          <ArtifactExtension payload={activeArtifact.payload} />
        {:else}
          <div class="unknown-kind">알 수 없는 아티팩트 유형</div>
        {/if}
      {:else}
        <div class="empty">아티팩트가 없습니다.</div>
      {/if}
    </div>

    <!-- 최대화 시 헤더가 사라지므로, 본문 위에 떠 있는 복귀 버튼을 둔다. 평소 옅게,
         hover/진입직후 또렷하게. -->
    {#if ui.artifactMaximized}
      <button
        class="restore-btn"
        class:hint={restoreHint}
        onclick={toggleArtifactMaximize}
        title="패널 모드로 복귀"
        aria-label="패널 모드로 복귀"
      >
        <svg
          width="15"
          height="15"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M2 6h4V2M14 10h-4v4M10 2v4h4M6 14v-4H2" />
        </svg>
        패널로 복귀
      </button>
    {/if}
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
    animation: panel-slide-in var(--dur-slow) ease-out;
    overflow: hidden;
    flex-shrink: 0;
    position: relative;
  }

  .artifact-panel.resizing {
    user-select: none;
    cursor: ew-resize;
  }

  /* 최대화 — 사이드바·채팅까지 덮어 뷰포트 전체 사용. 라이트박스(z 9999)·모달 아래. */
  .artifact-panel.maximized {
    position: fixed;
    inset: 0;
    width: 100% !important;
    z-index: 60;
    border-left: none;
    box-shadow: none;
  }

  /* 최대화 시 패널 크롬(헤더·탭·리사이즈 핸들) 숨김 — 본문만 전체 화면. */
  .artifact-panel.maximized .resize-handle,
  .artifact-panel.maximized .panel-header,
  .artifact-panel.maximized .tab-bar {
    display: none;
  }

  /* 떠 있는 복귀 버튼 — 본문 위 우상단. 평소 옅게, hover/진입 hint 시 또렷하게. */
  .restore-btn {
    position: absolute;
    top: 12px;
    right: 16px;
    z-index: 62;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 600;
    color: var(--fg);
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    border-radius: var(--radius-full);
    box-shadow: var(--shadow-md);
    cursor: pointer;
    opacity: 0.3;
    transition: opacity var(--dur-slow), background var(--dur-fast);
  }

  .restore-btn:hover,
  .restore-btn.hint {
    opacity: 1;
    background: var(--bg-hover);
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
    transition: background var(--dur-fast);
    touch-action: none;
  }

  .resize-handle:hover,
  .artifact-panel.resizing .resize-handle {
    background: var(--accent-border);
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
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    font-weight: 600;
    color: var(--fg);
    overflow: hidden;
    white-space: nowrap;
    flex: 1;
    min-width: 0;
  }

  .panel-title-text {
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .panel-header-actions {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
  }

  .ref-btn {
    font-size: 12px;
    font-weight: 600;
    color: var(--accent);
    background: var(--accent-soft);
    border: 1px solid var(--accent-border);
    border-radius: var(--radius-sm);
    padding: 3px 9px;
    cursor: pointer;
    white-space: nowrap;
    transition: background var(--dur-fast);
  }

  .ref-btn:hover {
    background: var(--accent-soft-strong);
  }

  .folder-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border: none;
    background: transparent;
    color: var(--fg-muted);
    cursor: pointer;
    border-radius: var(--radius-sm);
    flex-shrink: 0;
    transition: background var(--dur-fast), color var(--dur-fast);
  }

  .folder-btn:hover {
    background: var(--bg-hover);
    color: var(--fg);
  }

  .folder-btn.failed {
    color: var(--danger);
    background: var(--danger-bg);
    animation: folder-btn-shake 0.3s ease;
  }

  @keyframes folder-btn-shake {
    25% {
      transform: translateX(-2px);
    }
    75% {
      transform: translateX(2px);
    }
  }

  .maximize-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border: none;
    background: transparent;
    color: var(--fg-muted);
    cursor: pointer;
    border-radius: var(--radius-sm);
    flex-shrink: 0;
    transition: background var(--dur-fast), color var(--dur-fast);
  }

  .maximize-btn:hover {
    background: var(--bg-hover);
    color: var(--fg);
  }

  .close-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border: none;
    background: transparent;
    color: var(--fg-muted);
    cursor: pointer;
    border-radius: var(--radius-sm);
    flex-shrink: 0;
    transition: background var(--dur-fast), color var(--dur-fast);
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
    transition: background var(--dur-fast);
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

  .tab-close {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 14px;
    height: 14px;
    margin-left: 2px;
    border-radius: var(--radius-full);
    font-size: 13px;
    line-height: 1;
    color: var(--fg-subtle);
    flex-shrink: 0;
  }

  .tab-close:hover {
    background: var(--bg-active);
    color: var(--fg);
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
