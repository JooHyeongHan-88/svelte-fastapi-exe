<script>
  import ChartCell from "./ChartCell.svelte";

  // 표시 선택된 선택키들의 차트를 제목 패널 + 페이지네이션 그리드로 보여준다
  // (메인 앱 ArtifactChart 패턴). 셀 클릭은 라이트박스 확대로 위임한다. mark·roles·
  // aggregate 는 모든 셀에 공통 적용되는 차트 설정이다.
  let {
    charts = [],
    mark = "scatter",
    roles = { x: true, y: true, legend: true },
    aggregate = "mean",
    onopen = null,
  } = $props();

  const PAGE_SIZE = 12;

  let total = $derived(charts.length);
  let totalPages = $derived(Math.max(1, Math.ceil(total / PAGE_SIZE)));
  let page = $state(1);

  // charts 목록이 바뀌면 범위를 클램프한다(선택 추가/제거 시 빈 페이지 방지).
  $effect(() => {
    if (page > totalPages) page = totalPages;
    if (page < 1) page = 1;
  });

  let visible = $derived(charts.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE));

  function goPrev() {
    if (page > 1) page -= 1;
  }
  function goNext() {
    if (page < totalPages) page += 1;
  }
</script>

<div class="grid-wrap">
  {#if total === 0}
    <div class="empty">
      좌측에서 항목을 클릭해 차트를 표시하세요.<br />
      <span class="muted small">Ctrl(⌘)+클릭 토글 · Shift+클릭 범위 · '전체 보기'로 한 번에 볼 수 있습니다.</span>
    </div>
  {:else}
    <div class="toolbar">
      <span class="label">
        {#if total === 1}
          {charts[0]?.title || "차트"}
        {:else}
          차트 그리드 · {total}개
        {/if}
      </span>
      {#if totalPages > 1}
        <div class="pager" role="group" aria-label="페이지 네비게이션">
          <button class="page-btn" onclick={goPrev} disabled={page <= 1} aria-label="이전 페이지">‹</button>
          <span class="page-counter">{page} / {totalPages}</span>
          <button class="page-btn" onclick={goNext} disabled={page >= totalPages} aria-label="다음 페이지">›</button>
        </div>
      {/if}
    </div>

    {#if total === 1}
      <div class="single">
        {#key charts[0].key}
          <ChartCell
            chartKey={charts[0].key}
            points={charts[0].points}
            title={charts[0].title}
            {mark}
            {roles}
            {aggregate}
            xName={charts[0].xName}
            yName={charts[0].yName}
            embedded={false}
            onclick={() => onopen?.(0)}
          />
        {/key}
      </div>
    {:else}
      {#key page}
        <div class="grid">
          {#each visible as c, idx (c.key)}
            {@const globalIndex = (page - 1) * PAGE_SIZE + idx}
            <ChartCell
              chartKey={c.key}
              points={c.points}
              title={c.title}
              {mark}
              {roles}
              {aggregate}
              xName={c.xName}
              yName={c.yName}
              embedded={true}
              onclick={() => onopen?.(globalIndex)}
            />
          {/each}
        </div>
      {/key}
    {/if}
  {/if}
</div>

<style>
  .grid-wrap {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    overflow: hidden;
  }
  .toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 8px 14px;
    border-bottom: 1px solid var(--border);
    background: var(--panel-2);
    flex-shrink: 0;
  }
  .label {
    font-size: 12px;
    font-weight: 600;
    color: var(--fg);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
  }
  .pager {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    flex-shrink: 0;
  }
  .page-btn {
    width: 26px;
    height: 26px;
    border: 1px solid var(--border);
    background: var(--panel);
    border-radius: var(--radius-sm);
    color: var(--fg);
    font-size: 16px;
    line-height: 1;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .page-btn:hover:not(:disabled) {
    background: var(--panel-2);
    border-color: var(--accent-border);
  }
  .page-btn:disabled {
    opacity: 0.35;
    cursor: default;
  }
  .page-counter {
    font-size: 11px;
    color: var(--muted);
    font-variant-numeric: tabular-nums;
    padding: 0 6px;
  }
  .single {
    flex: 1;
    padding: 8px;
    min-height: 0;
  }
  .grid {
    flex: 1;
    overflow-y: auto;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 12px;
    padding: 12px;
    align-content: start;
  }
  .empty {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 4px;
    color: var(--muted);
    font-size: 13px;
    text-align: center;
  }
  .muted {
    color: var(--subtle);
  }
  .small {
    font-size: 12px;
  }
</style>
