<script>
  import { onDestroy } from "svelte";
  import * as echarts from "echarts";
  import { buildChartOption } from "./chartOption.js";
  import { currentSnapshot } from "./chartState.svelte.js";

  // 단일 ECharts 차트의 생명주기를 자가 관리한다(메인 앱 ChartCell 패턴 복사).
  // points + 뷰 스냅샷(currentSnapshot) + mark(차트 종류)로 option 을 만들고, brush
  // 환원용 row_ids 를 onchart 콜백으로 라이트박스에 넘긴다.
  let {
    chartKey,
    points = [],
    title = "",
    mark = "scatter",
    roles = { x: true, y: true, legend: true },
    aggregate = "mean",
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

  // 뷰 스냅샷·mark·매핑을 반응적으로 읽어 option 을 파생한다 — 변경 시 자동 재구성.
  // 제목은 감싼 패널(.cell-title / 라이트박스 헤더)이 표시하므로 차트에 넣지 않는다.
  let built = $derived(
    buildChartOption(mark, points, currentSnapshot(chartKey), {
      xName,
      yName,
      roles,
      aggregate,
    }),
  );

  // 매핑 누락 등으로 차트를 못 그리는 경우(option=null) 안내 문구.
  let buildError = $derived(built?.error ?? null);

  function emitChart() {
    if (chart && typeof onchart === "function") onchart(chart, built.row_ids);
  }

  function disposeChart() {
    resizeObserver?.disconnect();
    resizeObserver = null;
    chart?.dispose();
    chart = null;
  }

  // container 와 유효한 option 이 모두 준비됐을 때만 init/갱신한다. 차트 종류·매핑
  // 변경으로 option 이 null↔valid 를 오갈 수 있어 init 을 효과 안에서 일원화한다.
  function renderInto() {
    if (!container || !built?.option) return;
    try {
      if (!chart) {
        chart = echarts.init(container, null, { renderer: "canvas" });
        resizeObserver = new ResizeObserver(() => chart?.resize());
        resizeObserver.observe(container);
      }
      chart.setOption(built.option, { notMerge: true });
      renderError = null;
      emitChart();
    } catch (err) {
      disposeChart();
      renderError = err?.message ?? "알 수 없는 오류";
    }
  }

  onDestroy(disposeChart);

  // built(점·mark·매핑·스냅샷)·container 변화에 반응. 그릴 수 없으면 기존 차트를
  // 폐기해 stale 캔버스가 남지 않게 한다(매핑 누락으로 안내 문구를 띄울 때).
  $effect(() => {
    void built;
    void container;
    if (buildError || !built?.option || !container) {
      if (chart) disposeChart();
      return;
    }
    renderInto();
  });

  function handleClick() {
    if (typeof onclick === "function") onclick();
  }

  let clickable = $derived(typeof onclick === "function");
  let errorText = $derived(renderError ?? buildError);
</script>

<div class="chart-cell" class:embedded class:standalone={!embedded}>
  {#if embedded && title}
    <div class="cell-title" {title}>{title}</div>
  {/if}

  {#if errorText}
    <div class="cell-error">
      {#if renderError}
        <span>차트를 그릴 수 없습니다.</span>
        <small>{renderError}</small>
      {:else}
        <span class="needs-mapping">{buildError}</span>
      {/if}
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
  /* 매핑 누락은 에러가 아니라 안내 — 차분한 muted 색으로 표시. */
  .cell-error .needs-mapping {
    color: var(--muted);
  }
</style>
