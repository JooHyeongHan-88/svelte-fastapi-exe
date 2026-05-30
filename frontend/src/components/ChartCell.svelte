<script>
  import { onMount, onDestroy } from "svelte";
  import * as echarts from "echarts";

  // 단일 ECharts 인스턴스의 생명주기를 자가 관리한다.
  // ArtifactChart 가 each 로 여러 셀을 마운트/해제할 때 Svelte 가 자동으로
  // onMount/onDestroy 를 호출해주므로 dispose 누락 위험이 없다.

  let { item, onclick = null, onchart = null, embedded = true } = $props();

  let container = $state(null);
  let chart = null;
  let resizeObserver = null;
  let themeObserver = null;
  let renderError = $state(null);

  function isDark() {
    return document.documentElement.getAttribute("data-theme") === "dark";
  }

  // embedded(그리드) 셀은 클릭 시 라이트박스로 확대만 시키므로 ECharts 자체의
  // toolbox/brush/dataZoom 컨트롤은 노출하지 않는다. 컨트롤이 보이면 클릭이
  // 라이트박스 열기와 충돌해 사용자가 혼란스럽다.
  function optionForRender(raw) {
    if (!raw) return raw;
    if (!embedded) return raw;
    const { toolbox, brush, dataZoom, ...rest } = raw;
    return rest;
  }

  function initChart() {
    if (!container) return;
    if (chart) {
      chart.dispose();
      chart = null;
    }
    renderError = null;
    try {
      chart = echarts.init(container, isDark() ? "dark" : null, {
        renderer: "canvas",
      });
      chart.setOption(optionForRender(item.option));
      // standalone(lightbox) 에서만 ECharts 인스턴스를 노출한다.
      // 그리드 셀은 클릭=라이트박스 열기라 onchart 를 전달하지 않는다.
      if (typeof onchart === "function") onchart(chart);
    } catch (err) {
      chart?.dispose();
      chart = null;
      renderError = err?.message ?? "알 수 없는 오류";
    }
  }

  onMount(() => {
    initChart();
    resizeObserver = new ResizeObserver(() => chart?.resize());
    if (container) resizeObserver.observe(container);

    themeObserver = new MutationObserver(() => initChart());
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
  });

  onDestroy(() => {
    resizeObserver?.disconnect();
    themeObserver?.disconnect();
    chart?.dispose();
    chart = null;
  });

  // option 이 바뀌면 차트 갱신 (필터 결과 반영 / 페이지 내 같은 셀 재사용).
  $effect(() => {
    if (chart && item?.option) {
      try {
        chart.setOption(optionForRender(item.option), { notMerge: true });
        renderError = null;
        if (typeof onchart === "function") onchart(chart);
      } catch (err) {
        chart.dispose();
        chart = null;
        renderError = err?.message ?? "알 수 없는 오류";
      }
    }
  });

  function handleClick() {
    if (typeof onclick === "function") onclick();
  }

  let clickable = $derived(typeof onclick === "function");
</script>

<div class="chart-cell" class:embedded class:standalone={!embedded}>
  {#if embedded && item?.title}
    <div class="cell-title" title={item.title}>{item.title}</div>
  {/if}

  {#if renderError}
    <div class="cell-error">
      <span class="error-icon">📊</span>
      <span>차트를 그릴 수 없습니다.</span>
      <small>{renderError}</small>
    </div>
  {:else if clickable}
    <button
      type="button"
      class="cell-btn"
      onclick={handleClick}
      aria-label={item?.title || "차트 확대"}
    >
      <div class="chart-container" bind:this={container}></div>
    </button>
  {:else}
    <!-- standalone(lightbox)에서는 button 으로 감싸면 disabled 스타일로 인해
         canvas 가 흐려지고 pointer 이벤트가 차단돼 ECharts 컨트롤이 죽는다.
         컨테이너만 단독 렌더링한다. -->
    <div class="chart-container" bind:this={container}></div>
  {/if}
</div>

<style>
  .chart-cell {
    display: flex;
    flex-direction: column;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
    min-height: 0;
  }

  .chart-cell.embedded {
    height: 260px;
  }

  .chart-cell.standalone {
    height: 100%;
    border: none;
    background: transparent;
  }

  .cell-title {
    font-size: 11.5px;
    font-weight: 600;
    color: var(--fg);
    padding: 6px 10px;
    border-bottom: 1px solid var(--border);
    background: var(--bg-elevated);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex-shrink: 0;
  }

  .cell-btn {
    flex: 1;
    min-height: 0;
    padding: 0;
    border: none;
    background: transparent;
    cursor: zoom-in;
    transition: background 0.12s;
    width: 100%;
  }

  .cell-btn:disabled {
    cursor: default;
  }

  .cell-btn:hover:not(:disabled) {
    background: var(--bg-hover);
  }

  .chart-container {
    width: 100%;
    height: 100%;
  }

  .cell-error {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 16px;
    color: var(--color-danger, #e53e3e);
    font-size: 12px;
    text-align: center;
  }

  .cell-error .error-icon {
    font-size: 22px;
  }

  .cell-error small {
    font-size: 10px;
    color: var(--fg-muted);
    word-break: break-all;
  }
</style>
