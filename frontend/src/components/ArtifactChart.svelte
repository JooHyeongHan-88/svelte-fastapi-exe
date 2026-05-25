<script>
  import { onMount, onDestroy } from "svelte";
  import * as echarts from "echarts";

  let { payload } = $props();

  let container = $state(null);
  let chart = null;
  let renderError = $state(null);

  function isDark() {
    return document.documentElement.getAttribute("data-theme") === "dark";
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
      chart.setOption(payload.option);
    } catch (err) {
      chart?.dispose();
      chart = null;
      renderError = err?.message ?? "알 수 없는 오류";
    }
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
      try {
        chart.setOption(payload.option, { notMerge: true });
        renderError = null;
      } catch (err) {
        chart.dispose();
        chart = null;
        renderError = err?.message ?? "알 수 없는 오류";
      }
    }
  });
</script>

{#if renderError}
  <div class="artifact-error">
    <span class="error-icon">📊</span>
    <span>차트를 그릴 수 없습니다.</span>
    <small>{renderError}</small>
  </div>
{:else}
  <div class="chart-wrap">
    <div class="chart-container" bind:this={container}></div>
  </div>
{/if}

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

  .artifact-error {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    height: 100%;
    padding: 24px;
    margin: 16px;
    border: 2px dashed var(--color-danger, #e53e3e);
    border-radius: var(--radius);
    color: var(--color-danger, #e53e3e);
    font-size: 13px;
    text-align: center;
  }

  .artifact-error .error-icon {
    font-size: 28px;
  }

  .artifact-error small {
    font-size: 11px;
    color: var(--fg-muted);
    word-break: break-all;
    max-width: 100%;
  }
</style>
