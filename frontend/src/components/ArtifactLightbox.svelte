<script>
  import { onMount, onDestroy } from "svelte";
  import { ui } from "../lib/state.svelte.js";
  import {
    closeLightbox,
    lightboxNext,
    lightboxPrev,
    filterChartSelection,
    undoChartFilter,
    redoChartFilter,
    resetChartFilter,
    excludeLegend,
    setChartLegend,
  } from "../lib/artifactActions.svelte.js";
  import ChartCell from "./ChartCell.svelte";

  // ECharts 기본 팔레트 — 색상 오버라이드 전 스와치 표시용(시리즈에 명시 색이 없을 때).
  const ECHARTS_PALETTE = [
    "#5470c6", "#91cc75", "#fac858", "#ee6666", "#73c0de",
    "#3ba272", "#fc8452", "#9a60b4", "#ea7ccc",
  ];

  const MIN_WIDTH = 320;
  const MIN_HEIGHT = 240;
  const MAX_VW_RATIO = 0.95;
  const MAX_VH_RATIO = 0.95;
  const INITIAL_VW_RATIO = 0.8;
  const INITIAL_VH_RATIO = 0.8;

  let width = $state(720);
  let height = $state(560);

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function setInitialSize() {
    width = Math.round(window.innerWidth * INITIAL_VW_RATIO);
    height = Math.round(window.innerHeight * INITIAL_VH_RATIO);
  }

  $effect(() => {
    if (ui.lightbox.open) setInitialSize();
  });

  // ── 드래그 리사이즈 ────────────────────────────────────────────────
  let resizing = $state(false);
  let dragStart = { x: 0, y: 0, w: 0, h: 0 };

  function onResizePointerDown(e) {
    if (e.button !== 0) return;
    resizing = true;
    dragStart = { x: e.clientX, y: e.clientY, w: width, h: height };
    e.currentTarget.setPointerCapture?.(e.pointerId);
    e.preventDefault();
  }

  function onResizePointerMove(e) {
    if (!resizing) return;
    const dx = e.clientX - dragStart.x;
    const dy = e.clientY - dragStart.y;
    width = clamp(
      dragStart.w + dx * 2,
      MIN_WIDTH,
      Math.floor(window.innerWidth * MAX_VW_RATIO),
    );
    height = clamp(
      dragStart.h + dy * 2,
      MIN_HEIGHT,
      Math.floor(window.innerHeight * MAX_VH_RATIO),
    );
  }

  function onResizePointerUp(e) {
    if (!resizing) return;
    resizing = false;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
  }

  // ── 키보드 ────────────────────────────────────────────────────────
  function onKeydown(e) {
    if (!ui.lightbox.open) return;
    if (e.key === "Escape") {
      e.preventDefault();
      closeLightbox();
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      lightboxPrev();
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      lightboxNext();
    }
  }

  onMount(() => {
    window.addEventListener("keydown", onKeydown);
  });

  onDestroy(() => {
    window.removeEventListener("keydown", onKeydown);
  });

  function onBackdropClick(e) {
    if (e.target === e.currentTarget) closeLightbox();
  }

  function onBackdropKeydown(e) {
    if (e.target !== e.currentTarget) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      closeLightbox();
    }
  }

  // ── 차트 항목 (chartCache 경유) ────────────────────────────────────
  let chartItems = $derived(
    ui.lightbox.kind === "chart" && ui.lightbox.chartKey
      ? (ui.chartCache[ui.lightbox.chartKey]?.items ?? [])
      : [],
  );
  let canUndo = $derived(
    ui.lightbox.kind === "chart"
      ? (ui.chartCache[ui.lightbox.chartKey]?.canUndo ?? false)
      : false,
  );
  let canRedo = $derived(
    ui.lightbox.kind === "chart"
      ? (ui.chartCache[ui.lightbox.chartKey]?.canRedo ?? false)
      : false,
  );
  let hasFilter = $derived(
    ui.lightbox.kind === "chart"
      ? canUndo  // 필터가 적용됐으면 undo 가 가능하다
      : false,
  );

  // 이미지는 lightbox.items, 차트는 chartCache 항목
  let current = $derived(
    ui.lightbox.kind === "chart"
      ? (chartItems[ui.lightbox.index] ?? null)
      : (ui.lightbox.items[ui.lightbox.index] ?? null),
  );
  let total = $derived(
    ui.lightbox.kind === "chart" ? chartItems.length : ui.lightbox.items.length,
  );
  let hasMultiple = $derived(total > 1);

  // 현재 차트가 점 기반(row_ids 존재)인지 여부 — Filter/Filter All 활성화 조건.
  let currentHasRowIds = $derived(
    ui.lightbox.kind === "chart" && current?.row_ids != null,
  );

  // ── Brush 선택 관리 ──────────────────────────────────────────────
  // 현재 라이트박스 ECharts 인스턴스와 brush 선택 상태.
  let chartInstance = $state(null);
  let selectedRowIds = $state([]);   // 선택된 원본 parquet 행 인덱스
  let filterBusy = $state(false);    // API 요청 중 버튼 비활성

  function onChartReady(chart) {
    chartInstance = chart;
    selectedRowIds = [];

    // 기존 리스너 정리 후 새 인스턴스에 brushselected 이벤트 등록
    chart.off("brushselected");
    chart.on("brushselected", (params) => {
      const rowIds = [];
      const selected = params?.batch?.[0]?.selected ?? [];
      for (const seriesSel of selected) {
        const si = seriesSel.seriesIndex;
        const seriesRowIds = current?.row_ids?.[si];
        if (!seriesRowIds) continue;
        for (const di of seriesSel.dataIndex) {
          const rid = seriesRowIds[di];
          if (rid != null) rowIds.push(rid);
        }
      }
      selectedRowIds = [...new Set(rowIds)];
    });

    // brush 모드를 rect 로 기본 활성화 (드래그로 영역 선택)
    chart.dispatchAction({
      type: "takeGlobalCursor",
      key: "brush",
      brushOption: { brushType: "rect", brushMode: "single" },
    });
  }

  // ── 레전드 컨트롤 상태 ───────────────────────────────────────────
  let legendPanelOpen = $state(false);
  let selectedLegend = $state([]);   // Filter 대상으로 체크한 레전드 이름
  let dragIndex = $state(-1);        // 순서 변경 드래그 중인 행 인덱스

  // 현재 차트의 레전드 항목·색상·숨김 상태를 렌더된 option 단일 소스에서 파생한다.
  let legendNames = $derived(current?.option?.legend?.data ?? []);
  let legendEnabled = $derived(
    ui.lightbox.kind === "chart" && Array.isArray(legendNames) && legendNames.length > 1,
  );
  let legendColors = $derived.by(() => {
    const opt = current?.option;
    const names = opt?.legend?.data ?? [];
    const series = opt?.series ?? [];
    const map = {};
    names.forEach((name, i) => {
      const s = series.find((x) => x.name === name && x.itemStyle?.color);
      map[name] = s?.itemStyle?.color ?? ECHARTS_PALETTE[i % ECHARTS_PALETTE.length];
    });
    return map;
  });
  let hiddenSet = $derived.by(() => {
    const sel = current?.option?.legend?.selected ?? {};
    return new Set(Object.keys(sel).filter((k) => sel[k] === false));
  });

  // 인덱스/모달 오픈 시 brush·레전드 선택 상태 초기화
  $effect(() => {
    ui.lightbox.index;
    ui.lightbox.open;
    selectedRowIds = [];
    selectedLegend = [];
    dragIndex = -1;
    chartInstance = null;
  });

  // 레전드가 없는 차트로 이동하면 편집 패널을 닫는다.
  $effect(() => {
    if (!legendEnabled) legendPanelOpen = false;
  });

  // ── 필터 버튼 핸들러 (brush 행 / 레전드 그룹 분기) ────────────────
  async function handleFilter(scope) {
    if (filterBusy) return;
    const useLegend = selectedLegend.length > 0;
    const useBrush = selectedRowIds.length > 0 && currentHasRowIds;
    if (!useLegend && !useBrush) return;
    filterBusy = true;
    try {
      if (useLegend) {
        await excludeLegend(scope, ui.lightbox.index, selectedLegend);
        selectedLegend = [];
      } else {
        await filterChartSelection(scope, ui.lightbox.index, selectedRowIds);
      }
      selectedRowIds = [];
      // 필터 후 brush 클리어
      chartInstance?.dispatchAction({ type: "brush", areas: [] });
    } finally {
      filterBusy = false;
    }
  }

  // ── 레전드 편집 핸들러 ───────────────────────────────────────────
  function toggleLegendPanel() {
    if (!legendEnabled) return;
    legendPanelOpen = !legendPanelOpen;
  }

  function toggleSelectLegend(name) {
    selectedLegend = selectedLegend.includes(name)
      ? selectedLegend.filter((n) => n !== name)
      : [...selectedLegend, name];
  }

  async function toggleHide(name) {
    if (filterBusy) return;
    const next = new Set(hiddenSet);
    next.has(name) ? next.delete(name) : next.add(name);
    filterBusy = true;
    try {
      await setChartLegend(ui.lightbox.index, { hidden: [...next] });
    } finally {
      filterBusy = false;
    }
  }

  async function changeColor(name, hex) {
    if (filterBusy) return;
    filterBusy = true;
    try {
      await setChartLegend(ui.lightbox.index, { colors: { [name]: hex } });
    } finally {
      filterBusy = false;
    }
  }

  function onRowDragStart(i) {
    dragIndex = i;
  }

  async function onRowDrop(i) {
    const from = dragIndex;
    dragIndex = -1;
    if (from < 0 || from === i || filterBusy) return;
    const names = [...legendNames];
    const [moved] = names.splice(from, 1);
    names.splice(i, 0, moved);
    filterBusy = true;
    try {
      await setChartLegend(ui.lightbox.index, { order: names });
    } finally {
      filterBusy = false;
    }
  }

  async function handleUndo() {
    if (filterBusy || !canUndo) return;
    filterBusy = true;
    try { await undoChartFilter(); } finally { filterBusy = false; }
  }

  async function handleRedo() {
    if (filterBusy || !canRedo) return;
    filterBusy = true;
    try { await redoChartFilter(); } finally { filterBusy = false; }
  }

  async function handleReset() {
    if (filterBusy || !hasFilter) return;
    filterBusy = true;
    try { await resetChartFilter(); } finally { filterBusy = false; }
  }

  let hasSelection = $derived(selectedRowIds.length > 0);
  let hasLegendSelection = $derived(selectedLegend.length > 0);
  // Filter / Filter All 활성 조건: brush 점 선택(점 기반 차트) 또는 레전드 그룹 선택.
  let canFilter = $derived((hasSelection && currentHasRowIds) || hasLegendSelection);
  let specPresent = $derived(!!ui.lightbox.specPath);
</script>

{#if ui.lightbox.open && current}
  <div
    class="lightbox-backdrop"
    class:resizing
    role="dialog"
    aria-modal="true"
    aria-label="아티팩트 확대 보기"
    tabindex="-1"
    onclick={onBackdropClick}
    onkeydown={onBackdropKeydown}
  >
    <div
      class="lightbox-window"
      style="width: {width}px; height: {height}px"
    >
      <header class="lightbox-header">
        <span class="lightbox-title">
          {#if ui.lightbox.kind === "image"}
            {current.alt || current.caption || "이미지"}
          {:else if ui.lightbox.kind === "chart"}
            {current.title || "차트"}
          {/if}
        </span>
        <div class="header-actions">
          {#if hasMultiple}
            <span class="position-counter" aria-live="polite">
              {ui.lightbox.index + 1} / {total}
            </span>
          {/if}
          <button
            type="button"
            class="icon-btn"
            onclick={closeLightbox}
            aria-label="닫기"
            title="닫기 (Esc)"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none"
              stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <path d="M3 3l10 10M13 3 3 13" />
            </svg>
          </button>
        </div>
      </header>

      <!-- 차트 필터 컨트롤 툴바 (차트 전용) -->
      {#if ui.lightbox.kind === "chart" && specPresent}
        <div class="filter-toolbar">
          <!-- Filter / Filter All (brush 점 선택 또는 레전드 그룹 선택 시 활성) -->
          <button
            type="button"
            class="filter-btn"
            class:active={canFilter}
            disabled={!canFilter || filterBusy}
            onclick={() => handleFilter("single")}
            title={hasLegendSelection
              ? "선택한 레전드 그룹 제외"
              : currentHasRowIds
                ? "선택한 데이터 제외"
                : "선택(brush/레전드)이 없습니다"}
          >
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none"
              stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
              stroke-linejoin="round" aria-hidden="true">
              <path d="M1 3h14M4 8h8M7 13h2" />
            </svg>
            Filter
          </button>
          <button
            type="button"
            class="filter-btn"
            class:active={canFilter}
            disabled={!canFilter || filterBusy}
            onclick={() => handleFilter("all")}
            title={hasLegendSelection
              ? "선택한 레전드 그룹을 같은 데이터의 모든 차트에서 제외"
              : "같은 데이터의 모든 차트에 필터 적용"}
          >
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none"
              stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
              stroke-linejoin="round" aria-hidden="true">
              <path d="M1 3h14M4 8h8M7 13h2" />
              <circle cx="13" cy="13" r="3" fill="currentColor" stroke="none" />
            </svg>
            Filter All
          </button>

          <span class="toolbar-sep"></span>

          <!-- Legend 편집 토글 (레전드 항목 2개 이상일 때만 활성) -->
          <button
            type="button"
            class="filter-btn"
            class:active={legendPanelOpen}
            disabled={!legendEnabled}
            onclick={toggleLegendPanel}
            title={legendEnabled ? "레전드 순서·색상·표시 편집" : "레전드가 없는 차트입니다"}
          >
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none"
              stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
              stroke-linejoin="round" aria-hidden="true">
              <circle cx="4" cy="4" r="2" fill="currentColor" stroke="none" />
              <path d="M8 4h7" />
              <circle cx="4" cy="11" r="2" fill="currentColor" stroke="none" />
              <path d="M8 11h7" />
            </svg>
            Legend
          </button>

          <span class="toolbar-sep"></span>

          <!-- Undo -->
          <button
            type="button"
            class="icon-btn"
            disabled={!canUndo || filterBusy}
            onclick={handleUndo}
            title="되돌리기"
            aria-label="되돌리기"
          >
            <span class="material-symbols-outlined" aria-hidden="true">undo</span>
          </button>

          <!-- Redo -->
          <button
            type="button"
            class="icon-btn"
            disabled={!canRedo || filterBusy}
            onclick={handleRedo}
            title="다시 실행"
            aria-label="다시 실행"
          >
            <span class="material-symbols-outlined" aria-hidden="true">redo</span>
          </button>

          <!-- Reset -->
          <button
            type="button"
            class="icon-btn"
            disabled={!hasFilter || filterBusy}
            onclick={handleReset}
            title="초기화"
            aria-label="초기화"
          >
            <span class="material-symbols-outlined" aria-hidden="true">refresh</span>
          </button>
        </div>
      {/if}

      <!-- 본문 + 우측 레전드 편집 패널 (가로 배치) -->
      <div class="lightbox-main">
        <div class="lightbox-body">
          {#if ui.lightbox.kind === "image"}
            {#key ui.lightbox.index}
              <img
                src={current.src}
                alt={current.alt || ""}
                class="lightbox-image"
              />
            {/key}
          {:else if ui.lightbox.kind === "chart"}
            {#key ui.lightbox.index}
              <div class="lightbox-chart">
                <ChartCell item={current} embedded={false} onchart={onChartReady} />
              </div>
            {/key}
          {/if}

          {#if hasMultiple}
            <button
              type="button"
              class="nav-btn nav-prev"
              onclick={lightboxPrev}
              aria-label="이전 항목"
              title="이전 (←)"
            >
              ‹
            </button>
            <button
              type="button"
              class="nav-btn nav-next"
              onclick={lightboxNext}
              aria-label="다음 항목"
              title="다음 (→)"
            >
              ›
            </button>
          {/if}
        </div>

        <!-- 레전드 편집 패널 (순서 드래그 · 색상 · Hide · Filter 선택) -->
        {#if ui.lightbox.kind === "chart" && specPresent && legendPanelOpen && legendEnabled}
          <aside class="legend-panel">
            <div class="legend-panel-header">레전드</div>
            <div class="legend-hint">
              드래그로 순서 변경 · 색상 클릭 변경 · 눈으로 표시/숨김 ·
              체크 후 툴바의 Filter 로 데이터 제외
            </div>
            <ul class="legend-list">
              {#each legendNames as name, i (name)}
                <li
                  class="legend-row"
                  class:dragging={dragIndex === i}
                  draggable="true"
                  ondragstart={() => onRowDragStart(i)}
                  ondragover={(e) => e.preventDefault()}
                  ondrop={() => onRowDrop(i)}
                  ondragend={() => (dragIndex = -1)}
                >
                  <span class="drag-handle" aria-hidden="true">
                    <span class="material-symbols-outlined">drag_indicator</span>
                  </span>

                  <label class="legend-check" title="Filter 대상으로 선택">
                    <input
                      type="checkbox"
                      checked={selectedLegend.includes(name)}
                      onchange={() => toggleSelectLegend(name)}
                    />
                  </label>

                  <label class="color-swatch" title="색상 변경">
                    <span
                      class="swatch-dot"
                      style="background: {legendColors[name]}"
                    ></span>
                    <input
                      type="color"
                      value={legendColors[name]}
                      disabled={filterBusy}
                      onchange={(e) => changeColor(name, e.currentTarget.value)}
                    />
                  </label>

                  <span
                    class="legend-name"
                    class:hidden-name={hiddenSet.has(name)}
                    title={name}
                  >
                    {name}
                  </span>

                  <button
                    type="button"
                    class="eye-btn"
                    disabled={filterBusy}
                    onclick={() => toggleHide(name)}
                    title={hiddenSet.has(name) ? "표시" : "숨김"}
                    aria-label={hiddenSet.has(name) ? "표시" : "숨김"}
                  >
                    <span class="material-symbols-outlined">
                      {hiddenSet.has(name) ? "visibility_off" : "visibility"}
                    </span>
                  </button>
                </li>
              {/each}
            </ul>
          </aside>
        {/if}
      </div>

      {#if ui.lightbox.kind === "image" && current.caption}
        <footer class="lightbox-caption">{current.caption}</footer>
      {/if}

      <div
        class="resize-handle"
        role="separator"
        aria-orientation="horizontal"
        aria-label="모달 크기 조절"
        onpointerdown={onResizePointerDown}
        onpointermove={onResizePointerMove}
        onpointerup={onResizePointerUp}
        onpointercancel={onResizePointerUp}
      >
        <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
          <path d="M2 12 L12 2 M6 12 L12 6 M10 12 L12 10" stroke="currentColor" stroke-width="1.5" fill="none" />
        </svg>
      </div>
    </div>
  </div>
{/if}

<style>
  .lightbox-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.55);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 9999;
    animation: fade-in 0.15s ease-out;
  }

  .lightbox-backdrop.resizing {
    cursor: nwse-resize;
    user-select: none;
  }

  @keyframes fade-in {
    from { opacity: 0; }
    to   { opacity: 1; }
  }

  .lightbox-window {
    position: relative;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.4);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    min-width: 320px;
    min-height: 240px;
    max-width: 95vw;
    max-height: 95vh;
  }

  .lightbox-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
    background: var(--bg-elevated);
    flex-shrink: 0;
  }

  .lightbox-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--fg);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
  }

  .header-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
  }

  .position-counter {
    font-size: 11px;
    color: var(--fg-muted);
    font-variant-numeric: tabular-nums;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 2px 8px;
  }

  /* ── 필터 툴바 ── */
  .filter-toolbar {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 5px 10px;
    border-bottom: 1px solid var(--border);
    background: var(--bg-elevated);
    flex-shrink: 0;
  }

  .filter-btn {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 11.5px;
    padding: 3px 9px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--bg);
    color: var(--fg-muted);
    cursor: pointer;
    white-space: nowrap;
    transition: background 0.12s, color 0.12s, border-color 0.12s;
    height: 26px;
  }

  .filter-btn:hover:not(:disabled) {
    background: var(--bg-hover);
    color: var(--fg);
  }

  .filter-btn.active:not(:disabled) {
    border-color: var(--accent);
    color: var(--accent);
  }

  .filter-btn:disabled,
  .icon-btn:disabled {
    opacity: 0.35;
    cursor: not-allowed;
  }

  .toolbar-sep {
    width: 1px;
    height: 18px;
    background: var(--border);
    margin: 0 4px;
    flex-shrink: 0;
  }

  /* ── 본문 + 우측 레전드 패널 가로 배치 ── */
  .lightbox-main {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: row;
  }

  /* ── 레전드 편집 패널 (모달 우측) ── */
  .legend-panel {
    width: 240px;
    flex-shrink: 0;
    border-left: 1px solid var(--border);
    background: var(--bg-elevated);
    overflow-y: auto;
    display: flex;
    flex-direction: column;
  }

  .legend-panel-header {
    font-size: 12px;
    font-weight: 600;
    color: var(--fg);
    padding: 8px 12px 6px;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }

  .legend-hint {
    font-size: 10.5px;
    color: var(--fg-muted);
    padding: 8px 12px 6px;
    line-height: 1.4;
  }

  .legend-list {
    list-style: none;
    margin: 0;
    padding: 0 6px 6px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .legend-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 3px 6px;
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    cursor: grab;
  }

  .legend-row:hover {
    background: var(--bg-hover);
  }

  .legend-row.dragging {
    opacity: 0.5;
    border-color: var(--accent);
  }

  .drag-handle {
    display: inline-flex;
    align-items: center;
    color: var(--fg-muted);
    cursor: grab;
  }

  .drag-handle .material-symbols-outlined {
    font-size: 16px;
  }

  .legend-check {
    display: inline-flex;
    align-items: center;
    cursor: pointer;
  }

  .legend-check input {
    cursor: pointer;
    margin: 0;
  }

  .color-swatch {
    position: relative;
    display: inline-flex;
    align-items: center;
    cursor: pointer;
  }

  .swatch-dot {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid var(--border);
    display: inline-block;
  }

  /* 네이티브 color input 은 스와치 점 뒤에 겹쳐 클릭 영역만 제공 (투명) */
  .color-swatch input[type="color"] {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    opacity: 0;
    border: none;
    padding: 0;
    cursor: pointer;
  }

  .legend-name {
    flex: 1;
    font-size: 12px;
    color: var(--fg);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .legend-name.hidden-name {
    color: var(--fg-muted);
    text-decoration: line-through;
  }

  .eye-btn {
    width: 24px;
    height: 24px;
    border: none;
    background: transparent;
    color: var(--fg-muted);
    cursor: pointer;
    border-radius: var(--radius-sm);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    transition: background 0.12s, color 0.12s;
  }

  .eye-btn:hover:not(:disabled) {
    background: var(--bg);
    color: var(--fg);
  }

  .eye-btn:disabled {
    opacity: 0.35;
    cursor: not-allowed;
  }

  .eye-btn .material-symbols-outlined {
    font-size: 16px;
  }

  /* 기존 icon-btn 재사용 (헤더의 닫기 버튼과 동일 토큰) */
  .icon-btn {
    width: 26px;
    height: 26px;
    border: none;
    background: transparent;
    color: var(--fg-muted);
    cursor: pointer;
    border-radius: var(--radius-sm);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: background 0.12s, color 0.12s;
  }

  .icon-btn:hover:not(:disabled) {
    background: var(--bg-hover);
    color: var(--fg);
  }

  /* Material Symbols 크기 — 26px 버튼에 맞춤 */
  .icon-btn .material-symbols-outlined {
    font-size: 18px;
    line-height: 1;
    user-select: none;
  }

  /* ── 본문 ── */
  .lightbox-body {
    position: relative;
    flex: 1;
    min-height: 0;
    min-width: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    background: var(--bg);
  }

  .lightbox-image {
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
    display: block;
  }

  .lightbox-chart {
    width: 100%;
    height: 100%;
    padding: 8px;
    box-sizing: border-box;
  }

  .lightbox-caption {
    padding: 8px 14px;
    border-top: 1px solid var(--border);
    background: var(--bg-elevated);
    font-size: 12px;
    color: var(--fg-muted);
    text-align: center;
    flex-shrink: 0;
  }

  .nav-btn {
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    width: 38px;
    height: 38px;
    border-radius: 50%;
    border: 1px solid var(--border);
    background: color-mix(in srgb, var(--bg) 85%, transparent);
    backdrop-filter: blur(4px);
    color: var(--fg);
    cursor: pointer;
    font-size: 22px;
    line-height: 1;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: background 0.12s, transform 0.12s;
  }

  .nav-btn:hover {
    background: var(--bg);
    transform: translateY(-50%) scale(1.05);
  }

  .nav-prev { left: 12px; }
  .nav-next { right: 12px; }

  .resize-handle {
    position: absolute;
    bottom: 0;
    right: 0;
    width: 18px;
    height: 18px;
    cursor: nwse-resize;
    display: flex;
    align-items: flex-end;
    justify-content: flex-end;
    color: var(--fg-muted);
    touch-action: none;
    user-select: none;
    z-index: 2;
  }

  .resize-handle:hover {
    color: var(--accent);
  }
</style>
