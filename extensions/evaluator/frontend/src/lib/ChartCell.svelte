<script>
  import { onDestroy } from "svelte";
  import * as echarts from "echarts";
  import { buildChartOption, ECHARTS_PALETTE } from "./chartOption.js";
  import { currentSnapshot } from "./chartState.svelte.js";
  import { themeState } from "./theme.svelte.js";

  // 현재 테마의 CSS 변수로 ECharts 테마 객체를 만든다(축/텍스트/그리드 색). 옵션이
  // 축 색을 지정하지 않으므로 이 테마 기본값이 다크에서 가독을 책임진다.
  function makeEchartsTheme() {
    const cs = getComputedStyle(document.documentElement);
    const v = (name, fallback) => cs.getPropertyValue(name).trim() || fallback;
    const fg = v("--fg", "#1f1e1d");
    const muted = v("--muted", "#6b6a64");
    const border = v("--border", "#e5e2d8");
    const axis = {
      axisLine: { lineStyle: { color: border } },
      axisTick: { lineStyle: { color: border } },
      axisLabel: { color: muted },
      splitLine: { lineStyle: { color: border } },
      nameTextStyle: { color: muted },
    };
    return {
      color: ECHARTS_PALETTE,
      backgroundColor: "transparent",
      textStyle: { color: fg },
      title: { textStyle: { color: fg }, subtextStyle: { color: muted } },
      legend: { textStyle: { color: muted } },
      categoryAxis: axis,
      valueAxis: axis,
      logAxis: axis,
      timeAxis: axis,
      visualMap: { textStyle: { color: muted } },
      tooltip: {
        backgroundColor: v("--panel", "#ffffff"),
        borderColor: border,
        textStyle: { color: fg },
      },
    };
  }

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
  let chartTheme = null; // chart 가 init 된 테마 이름 — 변경 시 재init 트리거
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

  // embedded(그리드) 셀은 클릭=라이트박스 확대 전용이라 brush 박스 선택을 켜지 않는다.
  // standalone(라이트박스)에서만 brush 가 살아 있어야 드래그 선택이 가능하다.
  let renderOption = $derived.by(() => {
    const opt = built?.option;
    if (!opt || !embedded || !opt.brush) return opt;
    const { brush: _brush, ...rest } = opt;
    return rest;
  });

  function emitChart() {
    if (chart && typeof onchart === "function") onchart(chart, built.row_ids);
  }

  function disposeChart() {
    resizeObserver?.disconnect();
    resizeObserver = null;
    chart?.dispose();
    chart = null;
    chartTheme = null;
  }

  // container 와 유효한 option 이 모두 준비됐을 때만 init/갱신한다. 차트 종류·매핑
  // 변경으로 option 이 null↔valid 를 오갈 수 있어 init 을 효과 안에서 일원화한다.
  function renderInto() {
    if (!container || !built?.option) return;
    try {
      // 테마가 바뀌면 init 인자(테마)는 고정이라 dispose 후 재init 해야 반영된다.
      if (chart && chartTheme !== themeState.name) disposeChart();
      if (!chart) {
        chart = echarts.init(container, makeEchartsTheme(), { renderer: "canvas" });
        chartTheme = themeState.name;
        resizeObserver = new ResizeObserver(() => chart?.resize());
        resizeObserver.observe(container);
      }
      chart.setOption(renderOption, { notMerge: true });
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
    void themeState.name; // 테마 변경 시 재init(renderInto 가 dispose 후 새 테마로)
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
