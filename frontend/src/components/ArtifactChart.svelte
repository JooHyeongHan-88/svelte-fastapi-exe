<script>
  import { onMount, onDestroy } from "svelte";
  import * as echarts from "echarts";
  import { ui } from "../lib/state.svelte.js";

  let { payload } = $props();

  let container;
  let chart = null;

  function isDark() {
    return document.documentElement.getAttribute("data-theme") === "dark";
  }

  function initChart() {
    if (!container) return;
    if (chart) {
      chart.dispose();
    }
    chart = echarts.init(container, isDark() ? "dark" : null, {
      renderer: "canvas",
    });
    chart.setOption(payload.option);
  }

  // 테마 변경 감지 — data-theme attribute observer
  let themeObserver = null;

  onMount(() => {
    initChart();

    // 리사이즈 대응
    const resizeObserver = new ResizeObserver(() => chart?.resize());
    resizeObserver.observe(container);

    // 테마 변경 대응
    themeObserver = new MutationObserver(() => {
      initChart();
    });
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });

    return () => {
      resizeObserver.disconnect();
    };
  });

  onDestroy(() => {
    themeObserver?.disconnect();
    chart?.dispose();
  });

  // payload.option 변경 시 차트 갱신
  $effect(() => {
    if (chart && payload.option) {
      chart.setOption(payload.option, { notMerge: true });
    }
  });
</script>

<div class="chart-wrap">
  <div class="chart-container" bind:this={container}></div>
</div>

<style>
  .chart-wrap {
    display: flex;
    flex-direction: column;
    height: 100%;
    padding: 8px;
    box-sizing: border-box;
  }

  .chart-container {
    flex: 1;
    min-height: 0;
    width: 100%;
  }
</style>
