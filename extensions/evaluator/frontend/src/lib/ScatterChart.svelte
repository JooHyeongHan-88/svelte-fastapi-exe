<script>
  import { onMount, onDestroy } from "svelte";
  import * as echarts from "echarts";

  // 단일 ECharts 인스턴스의 생명주기를 자가 관리한다.
  // (메인 앱 ChartCell.svelte 의 init/dispose/ResizeObserver 패턴을 복사 — 격리 유지.)

  let { points = [], title = "", xName = "tkout_time", yName = "value" } = $props();

  let container = $state(null);
  let chart = null;
  let resizeObserver = null;

  // 레전드(category)별로 시리즈를 분리해 scatter option 을 구성한다.
  function buildOption(pts) {
    const groups = new Map();
    for (const p of pts) {
      const name = p.legend ?? "—";
      if (!groups.has(name)) groups.set(name, []);
      groups.get(name).push([p.x, p.y]);
    }
    const legendNames = [...groups.keys()];
    const series = legendNames.map((name) => ({
      name,
      type: "scatter",
      data: groups.get(name),
      symbolSize: 10,
      emphasis: { focus: "series" },
    }));

    return {
      title: title
        ? { text: title, left: 12, top: 8, textStyle: { fontSize: 13, fontWeight: 600 } }
        : undefined,
      tooltip: { trigger: "item" },
      legend: { data: legendNames, top: 8, right: 12 },
      grid: { left: 56, right: 28, top: 48, bottom: 60 },
      xAxis: {
        type: "time",
        name: xName,
        nameLocation: "middle",
        nameGap: 28,
      },
      yAxis: { type: "value", name: yName, scale: true },
      series,
    };
  }

  function initChart() {
    if (!container) return;
    if (chart) {
      chart.dispose();
      chart = null;
    }
    chart = echarts.init(container, null, { renderer: "canvas" });
    chart.setOption(buildOption(points));
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

  // points/title 가 바뀌면 차트를 즉시 갱신한다(라운드트립 없음 — 클라이언트 사이드 재구성).
  $effect(() => {
    if (chart) {
      chart.setOption(buildOption(points), { notMerge: true });
    }
  });
</script>

<div class="scatter" bind:this={container}></div>

<style>
  /* 부모가 flex 컨테이너일 때 flex:1 로 채운다 — height:100% 의 flex 아이템
     퍼센트-높이 미해석(ECharts 0 size 경고) 회피. */
  .scatter {
    flex: 1 1 auto;
    width: 100%;
    min-height: 0;
  }
</style>
