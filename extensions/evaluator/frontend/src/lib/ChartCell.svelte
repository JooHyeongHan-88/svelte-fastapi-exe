<script>
  import { onMount, onDestroy } from "svelte";
  import * as echarts from "echarts";
  import { buildScatterOption } from "./chartOption.js";
  import { currentSnapshot } from "./chartState.svelte.js";

  // 단일 ECharts scatter 의 생명주기를 자가 관리한다(메인 앱 ChartCell 패턴 복사).
  // points + 뷰 스냅샷(currentSnapshot)으로 option 을 만들고, brush 환원용 row_ids 를
  // onchart 콜백으로 라이트박스에 넘긴다.
  let {
    chartKey,
    points = [],
    title = "",
    xName = "x",
    yName = "y",
    embedded = true,
    onclick = null,
    onchart = null,
  } = $props();

  let container = $state(null);
  let chart = null;
  let resizeObserver = null;
  let renderError = $state(null);

  // 뷰 스냅샷을 반응적으로 읽어 option 을 파생한다 — 필터/레전드 변경 시 자동 재구성.
  // 제목은 감싼 패널(.cell-title / 라이트박스 헤더)이 표시하므로 차트에 넣지 않는다.
  let built = $derived(
    buildScatterOption(points, currentSnapshot(chartKey), { xName, yName }),
  );

  function emitChart() {
    if (chart && typeof onchart === "function") onchart(chart, built.row_ids);
  }

  function initChart() {
    if (!container) return;
    if (chart) {
      chart.dispose();
      chart = null;
    }
    renderError = null;
    try {
      chart = echarts.init(container, null, { renderer: "canvas" });
      chart.setOption(built.option);
      emitChart();
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
  });

  onDestroy(() => {
    resizeObserver?.disconnect();
    chart?.dispose();
    chart = null;
  });

  // option 이 바뀌면(필터/레전드/페이지 내 셀 재사용) 차트 갱신 + row_ids 재통지.
  $effect(() => {
    if (!chart || !built?.option) return;
    try {
      chart.setOption(built.option, { notMerge: true });
      renderError = null;
      emitChart();
    } catch (err) {
      chart.dispose();
      chart = null;
      renderError = err?.message ?? "알 수 없는 오류";
    }
  });

  function handleClick() {
    if (typeof onclick === "function") onclick();
  }

  let clickable = $derived(typeof onclick === "function");
</script>

<div class="chart-cell" class:embedded class:standalone={!embedded}>
  {#if embedded && title}
    <div class="cell-title" {title}>{title}</div>
  {/if}

  {#if renderError}
    <div class="cell-error">
      <span>차트를 그릴 수 없습니다.</span>
      <small>{renderError}</small>
    </div>
  {:else if clickable}
    <button type="button" class="cell-btn" onclick={handleClick} aria-label={title || "차트 확대"}>
      <div class="chart-container" bind:this={container}></div>
    </button>
  {:else}
    <!-- standalone(라이트박스)에서는 button 으로 감싸면 pointer 이벤트가 막혀 brush 가
         죽으므로 컨테이너만 단독 렌더링한다. -->
    <div class="chart-container" bind:this={container}></div>
  {/if}
</div>

<style>
  .chart-cell {
    display: flex;
    flex-direction: column;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
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
    background: var(--panel-2);
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
    width: 100%;
    transition: background var(--dur-fast, 0.12s);
  }
  .cell-btn:hover {
    background: var(--panel-2);
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
    color: var(--danger);
    font-size: 12px;
    text-align: center;
  }
  .cell-error small {
    font-size: 10px;
    color: var(--muted);
    word-break: break-all;
  }
</style>
