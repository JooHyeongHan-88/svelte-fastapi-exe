<script>
  import { onMount, onDestroy } from "svelte";
  import ChartCell from "./ChartCell.svelte";
  import { buildScatterOption, ECHARTS_PALETTE } from "./chartOption.js";
  import {
    currentSnapshot,
    applyExclude,
    applyLegend,
    reset as resetView,
    undo as undoView,
    redo as redoView,
    canUndo,
    canRedo,
    hasView,
  } from "./chartState.svelte.js";

  // 표시 선택된 차트 목록을 확대 보여주는 리사이즈 모달 — Filter/Filter All/Reset/Undo/Redo
  // 툴바 + 우측 레전드 편집 패널(메인 앱 ArtifactLightbox 의 evaluator 클라이언트 버전).
  let { charts = [], index = 0, onclose = null, onnext = null, onprev = null } = $props();

  const MIN_WIDTH = 320;
  const MIN_HEIGHT = 240;

  let width = $state(720);
  let height = $state(560);

  function clamp(v, min, max) {
    return Math.min(max, Math.max(min, v));
  }

  onMount(() => {
    width = Math.round(window.innerWidth * 0.8);
    height = Math.round(window.innerHeight * 0.8);
    window.addEventListener("keydown", onKeydown);
  });
  onDestroy(() => window.removeEventListener("keydown", onKeydown));

  // ── 현재 차트 ────────────────────────────────────────────────────
  let current = $derived(charts[index] ?? null);
  let chartKey = $derived(current?.key ?? null);
  let total = $derived(charts.length);
  let hasMultiple = $derived(total > 1);

  // 레전드 메타데이터는 같은 빌더로 파생한다(셀과 동일 결과 — 렌더는 셀이 자체 수행).
  let snap = $derived(chartKey ? currentSnapshot(chartKey) : null);
  let built = $derived(
    current
      ? buildScatterOption(current.points, snap, {
          xName: current.xName,
          yName: current.yName,
        })
      : null,
  );
  let legendNames = $derived(built?.legendNames ?? []);
  let legendEnabled = $derived(legendNames.length > 1);
  let legendColors = $derived.by(() => {
    const colors = snap?.legend?.colors ?? {};
    const map = {};
    legendNames.forEach((name, i) => {
      map[name] = colors[name] ?? ECHARTS_PALETTE[i % ECHARTS_PALETTE.length];
    });
    return map;
  });
  let hiddenSet = $derived(new Set(snap?.legend?.hidden ?? []));

  let cUndo = $derived(chartKey ? canUndo(chartKey) : false);
  let cRedo = $derived(chartKey ? canRedo(chartKey) : false);
  let cReset = $derived(chartKey ? hasView(chartKey) : false);

  // ── brush 선택 ───────────────────────────────────────────────────
  let chartInstance = $state(null);
  let currentRowIds = $state([]);
  let selectedRowIds = $state([]);
  let filterBusy = $state(false);

  function onChartReady(chart, rowIds) {
    chartInstance = chart;
    currentRowIds = rowIds ?? [];
    selectedRowIds = [];
    chart.off("brushselected");
    chart.on("brushselected", (params) => {
      const ids = [];
      const sel = params?.batch?.[0]?.selected ?? [];
      for (const s of sel) {
        const series = currentRowIds[s.seriesIndex];
        if (!series) continue;
        for (const di of s.dataIndex) {
          const rid = series[di];
          if (rid != null) ids.push(rid);
        }
      }
      selectedRowIds = [...new Set(ids)];
    });
    chart.dispatchAction({
      type: "takeGlobalCursor",
      key: "brush",
      brushOption: { brushType: "rect", brushMode: "single" },
    });
  }

  // ── 레전드 Filter 선택 + 드래그 ──────────────────────────────────
  let legendPanelOpen = $state(false);
  let selectedLegend = $state([]);
  let dragIndex = $state(-1);

  // 인덱스/선택이 바뀌면 brush·레전드 선택 초기화.
  $effect(() => {
    index;
    selectedRowIds = [];
    selectedLegend = [];
    dragIndex = -1;
    chartInstance = null;
  });
  $effect(() => {
    if (!legendEnabled) legendPanelOpen = false;
  });

  // points 에서 특정 레전드 이름들에 속한 인덱스를 모은다(레전드 Filter → 제외 환원).
  function indicesForLegend(points, nameSet) {
    const out = [];
    points.forEach((p, i) => {
      if (nameSet.has(p.legend ?? "—")) out.push(i);
    });
    return out;
  }

  async function handleFilter(scope) {
    if (filterBusy) return;
    const useLegend = selectedLegend.length > 0;
    const useBrush = selectedRowIds.length > 0;
    if (!useLegend && !useBrush) return;
    filterBusy = true;
    try {
      if (useLegend) {
        const nameSet = new Set(selectedLegend);
        if (scope === "all") {
          for (const c of charts) applyExclude(c.key, indicesForLegend(c.points, nameSet));
        } else {
          applyExclude(chartKey, indicesForLegend(current.points, nameSet));
        }
        selectedLegend = [];
      } else if (scope === "all") {
        // brush 점이 속한 레전드 값을 모든 차트에서 제외 — "Filter All" 의 의미.
        const nameSet = new Set(
          selectedRowIds.map((i) => current.points[i]?.legend ?? "—"),
        );
        for (const c of charts) applyExclude(c.key, indicesForLegend(c.points, nameSet));
      } else {
        applyExclude(chartKey, selectedRowIds);
      }
      selectedRowIds = [];
      chartInstance?.dispatchAction({ type: "brush", areas: [] });
    } finally {
      filterBusy = false;
    }
  }

  function handleUndo() {
    if (cUndo) undoView(chartKey);
  }
  function handleRedo() {
    if (cRedo) redoView(chartKey);
  }
  function handleReset() {
    if (cReset) resetView(chartKey);
  }

  // ── 레전드 편집 ───────────────────────────────────────────────────
  function toggleLegendPanel() {
    if (legendEnabled) legendPanelOpen = !legendPanelOpen;
  }
  function toggleSelectLegend(name) {
    selectedLegend = selectedLegend.includes(name)
      ? selectedLegend.filter((n) => n !== name)
      : [...selectedLegend, name];
  }
  function toggleHide(name) {
    const next = new Set(hiddenSet);
    next.has(name) ? next.delete(name) : next.add(name);
    applyLegend(chartKey, { hidden: [...next] });
  }
  function changeColor(name, hex) {
    applyLegend(chartKey, { colors: { [name]: hex } });
  }
  function onRowDragStart(i) {
    dragIndex = i;
  }
  function onRowDrop(i) {
    const from = dragIndex;
    dragIndex = -1;
    if (from < 0 || from === i) return;
    const names = [...legendNames];
    const [moved] = names.splice(from, 1);
    names.splice(i, 0, moved);
    applyLegend(chartKey, { order: names });
  }

  // ── 리사이즈 ──────────────────────────────────────────────────────
  let resizing = $state(false);
  let dragStart = { x: 0, y: 0, w: 0, h: 0 };
  function onResizeDown(e) {
    if (e.button !== 0) return;
    resizing = true;
    dragStart = { x: e.clientX, y: e.clientY, w: width, h: height };
    e.currentTarget.setPointerCapture?.(e.pointerId);
    e.preventDefault();
  }
  function onResizeMove(e) {
    if (!resizing) return;
    width = clamp(dragStart.w + (e.clientX - dragStart.x) * 2, MIN_WIDTH, Math.floor(window.innerWidth * 0.95));
    height = clamp(dragStart.h + (e.clientY - dragStart.y) * 2, MIN_HEIGHT, Math.floor(window.innerHeight * 0.95));
  }
  function onResizeUp(e) {
    if (!resizing) return;
    resizing = false;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
  }

  function onKeydown(e) {
    if (e.key === "Escape") {
      e.preventDefault();
      onclose?.();
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      onprev?.();
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      onnext?.();
    }
  }

  function onBackdrop(e) {
    if (e.target === e.currentTarget) onclose?.();
  }

  let hasLegendSelection = $derived(selectedLegend.length > 0);
  let canFilter = $derived(selectedRowIds.length > 0 || hasLegendSelection);
</script>

{#if current}
  <div class="lb-backdrop" class:resizing role="presentation" onclick={onBackdrop}>
    <div class="lb-window" style="width: {width}px; height: {height}px">
      <header class="lb-header">
        <span class="lb-title">{current.title || "차트"}</span>
        <div class="lb-head-actions">
          {#if hasMultiple}
            <span class="counter">{index + 1} / {total}</span>
          {/if}
          <button class="icon-btn" onclick={() => onclose?.()} title="닫기 (Esc)" aria-label="닫기">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 3l10 10M13 3 3 13" /></svg>
          </button>
        </div>
      </header>

      <div class="filter-toolbar">
        <button
          class="filter-btn"
          class:active={canFilter}
          disabled={!canFilter || filterBusy}
          onclick={() => handleFilter("single")}
          title={hasLegendSelection ? "선택한 레전드 그룹 제외" : "선택한 데이터 제외"}
        >
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M1 3h14M4 8h8M7 13h2" /></svg>
          Filter
        </button>
        <button
          class="filter-btn"
          class:active={canFilter}
          disabled={!canFilter || filterBusy}
          onclick={() => handleFilter("all")}
          title="표시 중인 모든 차트에 제외 적용"
        >
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M1 3h14M4 8h8M7 13h2" /><circle cx="13" cy="13" r="3" fill="currentColor" stroke="none" /></svg>
          Filter All
        </button>

        <span class="sep"></span>

        <button
          class="filter-btn"
          class:active={legendPanelOpen}
          disabled={!legendEnabled}
          onclick={toggleLegendPanel}
          title={legendEnabled ? "레전드 순서·색상·표시 편집" : "레전드가 없는 차트입니다"}
        >
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="4" cy="4" r="2" fill="currentColor" stroke="none" /><path d="M8 4h7" /><circle cx="4" cy="11" r="2" fill="currentColor" stroke="none" /><path d="M8 11h7" /></svg>
          Legend
        </button>

        <span class="sep"></span>

        <button class="icon-btn" disabled={!cUndo || filterBusy} onclick={handleUndo} title="되돌리기" aria-label="되돌리기">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 8h7a3 3 0 0 1 0 6H7" /><path d="M6 5 3 8l3 3" /></svg>
        </button>
        <button class="icon-btn" disabled={!cRedo || filterBusy} onclick={handleRedo} title="다시 실행" aria-label="다시 실행">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12.5 8h-7a3 3 0 0 0 0 6H9" /><path d="M10 5l3 3-3 3" /></svg>
        </button>
        <button class="icon-btn" disabled={!cReset || filterBusy} onclick={handleReset} title="초기화" aria-label="초기화">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M13.5 6A5.5 5.5 0 1 0 14 9" /><path d="M14 2.5V6h-3.5" /></svg>
        </button>
      </div>

      <div class="lb-main">
        <div class="lb-body">
          {#key index}
            <div class="lb-chart">
              <ChartCell
                chartKey={current.key}
                points={current.points}
                title={current.title}
                xName={current.xName}
                yName={current.yName}
                embedded={false}
                onchart={onChartReady}
              />
            </div>
          {/key}

          {#if hasMultiple}
            <button class="nav-btn nav-prev" onclick={() => onprev?.()} aria-label="이전" title="이전 (←)">‹</button>
            <button class="nav-btn nav-next" onclick={() => onnext?.()} aria-label="다음" title="다음 (→)">›</button>
          {/if}
        </div>

        {#if legendPanelOpen && legendEnabled}
          <aside class="legend-panel">
            <div class="legend-head">레전드</div>
            <div class="legend-hint">드래그 순서 · 색상 클릭 · 눈 표시/숨김 · 체크 후 Filter 로 제외</div>
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
                    <svg width="12" height="14" viewBox="0 0 12 14" fill="currentColor"><circle cx="4" cy="3" r="1.3" /><circle cx="8" cy="3" r="1.3" /><circle cx="4" cy="7" r="1.3" /><circle cx="8" cy="7" r="1.3" /><circle cx="4" cy="11" r="1.3" /><circle cx="8" cy="11" r="1.3" /></svg>
                  </span>
                  <label class="legend-check" title="Filter 대상 선택">
                    <input type="checkbox" checked={selectedLegend.includes(name)} onchange={() => toggleSelectLegend(name)} />
                  </label>
                  <label class="color-swatch" title="색상 변경">
                    <span class="swatch-dot" style="background: {legendColors[name]}"></span>
                    <input type="color" value={legendColors[name]} onchange={(e) => changeColor(name, e.currentTarget.value)} />
                  </label>
                  <span class="legend-name" class:hidden-name={hiddenSet.has(name)} title={name}>{name}</span>
                  <button class="eye-btn" onclick={() => toggleHide(name)} title={hiddenSet.has(name) ? "표시" : "숨김"} aria-label={hiddenSet.has(name) ? "표시" : "숨김"}>
                    {#if hiddenSet.has(name)}
                      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><path d="M2 2l12 12" /><path d="M6.5 6.6a2 2 0 0 0 2.8 2.8" /><path d="M4 4.2C2.3 5.2 1 8 1 8s2.5 5 7 5a7 7 0 0 0 2.8-.6" /><path d="M7 3.1A6.6 6.6 0 0 1 8 3c4.5 0 7 5 7 5a13 13 0 0 1-1.7 2.3" /></svg>
                    {:else}
                      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><path d="M1 8s2.5-5 7-5 7 5 7 5-2.5 5-7 5-7-5-7-5Z" /><circle cx="8" cy="8" r="2" /></svg>
                    {/if}
                  </button>
                </li>
              {/each}
            </ul>
          </aside>
        {/if}
      </div>

      <div class="resize-handle" role="separator" aria-label="크기 조절" onpointerdown={onResizeDown} onpointermove={onResizeMove} onpointerup={onResizeUp} onpointercancel={onResizeUp}>
        <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M2 12 L12 2 M6 12 L12 6 M10 12 L12 10" stroke="currentColor" stroke-width="1.5" fill="none" /></svg>
      </div>
    </div>
  </div>
{/if}

<style>
  .lb-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.45);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 100;
  }
  .lb-backdrop.resizing {
    cursor: nwse-resize;
    user-select: none;
  }
  .lb-window {
    position: relative;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    box-shadow: var(--shadow);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    min-width: 320px;
    min-height: 240px;
    max-width: 95vw;
    max-height: 95vh;
  }
  .lb-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
    background: var(--panel);
    flex-shrink: 0;
  }
  .lb-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--fg);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
  }
  .lb-head-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
  }
  .counter {
    font-size: 11px;
    color: var(--muted);
    font-variant-numeric: tabular-nums;
    background: var(--panel-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 2px 8px;
  }
  .filter-toolbar {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 5px 10px;
    border-bottom: 1px solid var(--border);
    background: var(--panel);
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
    color: var(--muted);
    white-space: nowrap;
    height: 28px;
  }
  .filter-btn:hover:not(:disabled) {
    background: var(--panel-2);
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
  .sep {
    width: 1px;
    height: 18px;
    background: var(--border);
    margin: 0 4px;
    flex-shrink: 0;
  }
  .icon-btn {
    width: 28px;
    height: 28px;
    border: none;
    background: transparent;
    color: var(--muted);
    border-radius: var(--radius-sm);
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .icon-btn:hover:not(:disabled) {
    background: var(--panel-2);
    color: var(--fg);
  }
  .lb-main {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: row;
  }
  .lb-body {
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
  .lb-chart {
    width: 100%;
    height: 100%;
    padding: 8px;
  }
  .nav-btn {
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    width: 38px;
    height: 38px;
    border-radius: 50%;
    border: 1px solid var(--border);
    background: var(--panel);
    color: var(--fg);
    font-size: 22px;
    line-height: 1;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .nav-btn:hover {
    background: var(--panel-2);
  }
  .nav-prev {
    left: 12px;
  }
  .nav-next {
    right: 12px;
  }
  .legend-panel {
    width: 240px;
    flex-shrink: 0;
    border-left: 1px solid var(--border);
    background: var(--panel);
    overflow-y: auto;
    display: flex;
    flex-direction: column;
  }
  .legend-head {
    font-size: 12px;
    font-weight: 600;
    color: var(--fg);
    padding: 8px 12px 6px;
    border-bottom: 1px solid var(--border);
  }
  .legend-hint {
    font-size: 10.5px;
    color: var(--muted);
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
    background: var(--panel-2);
  }
  .legend-row.dragging {
    opacity: 0.5;
    border-color: var(--accent);
  }
  .drag-handle {
    display: inline-flex;
    align-items: center;
    color: var(--subtle);
    cursor: grab;
  }
  .legend-check {
    display: inline-flex;
    align-items: center;
    cursor: pointer;
  }
  .legend-check input {
    cursor: pointer;
    margin: 0;
    accent-color: var(--accent);
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
    color: var(--muted);
    text-decoration: line-through;
  }
  .eye-btn {
    width: 24px;
    height: 24px;
    border: none;
    background: transparent;
    color: var(--muted);
    border-radius: var(--radius-sm);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
  .eye-btn:hover {
    background: var(--bg);
    color: var(--fg);
  }
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
    color: var(--subtle);
    touch-action: none;
    user-select: none;
    z-index: 2;
  }
  .resize-handle:hover {
    color: var(--accent);
  }
</style>
