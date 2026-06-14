<script>
  import { onMount } from "svelte";
  import {
    getDataset,
    getSources,
    getPreview,
    getState,
    saveState,
    exportCurated,
  } from "./lib/api.js";
  import ChartGrid from "./lib/ChartGrid.svelte";
  import ChartLightbox from "./lib/ChartLightbox.svelte";
  import { currentSnapshot } from "./lib/chartState.svelte.js";

  const MAPPING_KEYS = ["select", "sort", "x", "y", "legend", "desc"];

  let mapping = $state({}); // 공통 매핑 (번들/쿼리 — 소스 간 동일 스키마 전제)
  let loading = $state(true); // 초기 전체 로드
  let error = $state(null); // 치명적 에러 (소스 0개·번들 실패)

  let sources = $state([]); // 작업 세트: 소스 경로 배열
  let activeIdx = $state(0);

  // 활성 소스의 작업 상태 (탭 전환 시 stash 에서 복원).
  let items = $state([]); // [{key, sort, desc}]
  let pointsByKey = $state({}); // key -> [{x,y,legend}]
  let order = $state([]); // 표시 순서의 키 배열
  let selected = $state([]); // 체크된 키(order 의 부분집합 — 내보내기 대상)
  let cursor = $state(0); // 키보드 하이라이트된 항목 인덱스
  let displaySelection = $state([]); // 차트로 표시 중인 키 집합(Ctrl+클릭 다중 선택)
  let sourceLoading = $state(false); // 탭 전환 시 활성 소스 로딩
  let sourceError = $state(null); // 활성 소스 로드 실패 (탭 단위)

  let saving = $state(false);
  let exporting = $state(false);
  let status = $state(null); // {kind: "ok"|"err", text}
  let exportInfo = $state(null); // {path, rows, items}

  // 좌측 패널 너비(드래그 조절).
  let sidebarWidth = $state(320);
  let resizingSidebar = $state(false);

  // 차트 확대 라이트박스.
  let lightboxOpen = $state(false);
  let lightboxIndex = $state(0);

  // 소스 추가/변경 picker.
  let pickerOpen = $state(false);
  let pickerMode = $state("add"); // 'add' | 'change' (단일 소스는 변경)
  let catalog = $state([]); // /sources 결과
  let catalogLoading = $state(false);
  let pickedPath = $state(""); // 피커에서 미리보기 중인 후보 경로
  let preview = $state(null); // {filename, total_rows, schema, head}
  let previewLoading = $state(false);
  let previewError = $state(null);

  // 탭 전환 시 per-source 작업 상태 보존 (plain — 복원 시 $state 변수를 명시적 재할당).
  const stash = {};

  // 파생 상태
  let activePath = $derived(sources[activeIdx] ?? "");
  let selectedOrdered = $derived(order.filter((k) => selected.includes(k)));

  // 표시 선택된 키들의 차트 스펙(리스트 순서 유지). chartState 식별자는 소스 경로로
  // 네임스페이스해 소스 간 같은 키가 필터 상태를 공유하지 않게 한다.
  let displayCharts = $derived(
    order
      .filter((k) => displaySelection.includes(k))
      .map((k) => {
        const item = items.find((i) => i.key === k);
        const desc = item?.desc;
        return {
          key: `${activePath}::${k}`,
          title: desc ? `${k} — ${desc}` : k,
          points: pointsByKey[k] ?? [],
          xName: mapping.x,
          yName: mapping.y,
        };
      }),
  );

  // 표시 차트가 줄어 라이트박스 인덱스가 범위를 벗어나면 닫는다.
  $effect(() => {
    if (lightboxOpen && lightboxIndex >= displayCharts.length) lightboxOpen = false;
  });

  function fileName(p) {
    return p ? p.split("/").pop() : "";
  }

  function readUrl() {
    const q = new URLSearchParams(window.location.search);
    const m = {};
    for (const k of MAPPING_KEYS) {
      const v = q.get(k);
      if (v) m[k] = v;
    }
    return {
      path: q.get("path") || "",
      bundle: q.get("bundle") || "",
      queryMapping: m,
    };
  }

  // 번들(open_curation 산출)을 읽어 소스 목록·매핑을 확정한다. 번들은 result/...
  // 경로이며 호스트가 /result/ 로 서빙한다.
  async function fetchBundle(bundle) {
    const res = await fetch(encodeURI("/" + bundle), { cache: "no-cache" });
    if (!res.ok) throw new Error(`번들 로드 실패: HTTP ${res.status}`);
    const b = await res.json();
    const list = Array.isArray(b.sources) ? b.sources : [];
    if (list.length === 0) throw new Error("번들에 sources 가 없습니다.");
    const m = b.mapping && typeof b.mapping === "object" ? b.mapping : {};
    return { sources: list, mapping: m };
  }

  async function loadAll() {
    loading = true;
    error = null;
    try {
      const { path, bundle, queryMapping } = readUrl();
      mapping = queryMapping;
      let initial = [];
      if (bundle) {
        const b = await fetchBundle(bundle);
        initial = b.sources;
        mapping = { ...mapping, ...b.mapping };
      } else if (path) {
        initial = [path];
      }
      if (initial.length === 0)
        throw new Error("URL 에 ?path= 또는 ?bundle= 경로가 필요합니다.");
      sources = initial;
      activeIdx = 0;
      await loadActiveSource();
    } catch (e) {
      error = e?.message || String(e);
    } finally {
      loading = false;
    }
  }

  onMount(loadAll);

  // 활성 소스 데이터/상태를 작업 변수에 반영한다.
  function applyDataset(ds, st) {
    items = ds.items;
    mapping = ds.mapping; // 백엔드가 확정한 실제 매핑(기본값 채움)

    const pmap = {};
    for (const p of ds.points) {
      (pmap[p.key] ??= []).push({ x: p.x, y: p.y, legend: p.legend });
    }
    pointsByKey = pmap;

    const itemKeys = items.map((i) => i.key);
    const savedSelected = Array.isArray(st.selected) ? st.selected : [];
    const savedOrder = Array.isArray(st.order) ? st.order : [];
    // 저장된 순서가 현재 아이템 집합과 정확히 일치할 때만 복원, 아니면 sort 순서 유지.
    const validOrder =
      savedOrder.length === itemKeys.length &&
      savedOrder.every((k) => itemKeys.includes(k));
    order = validOrder ? savedOrder : itemKeys;

    // 저장된 상태가 전혀 없으면(신규 소스) 기본으로 전부 선택(체크)한다.
    const noSaved = savedSelected.length === 0 && savedOrder.length === 0;
    selected = noSaved
      ? [...itemKeys]
      : savedSelected.filter((k) => itemKeys.includes(k));

    cursor = 0;
    // 기본 표시 차트는 첫 항목 1개 — Ctrl+클릭으로 다중 표시.
    displaySelection = itemKeys.length > 0 ? [order[0]] : [];
  }

  function stashCurrent() {
    const p = sources[activeIdx];
    if (!p || sourceError) return;
    stash[p] = {
      items,
      pointsByKey,
      order: [...order],
      selected: [...selected],
      cursor,
      displaySelection: [...displaySelection],
    };
  }

  function restoreFromStash(p) {
    const s = stash[p];
    items = s.items;
    pointsByKey = s.pointsByKey;
    order = [...s.order];
    selected = [...s.selected];
    cursor = s.cursor;
    displaySelection = [...(s.displaySelection ?? [])];
    sourceError = null;
  }

  // 활성 소스(sources[activeIdx])를 작업 상태로 적재 — stash 우선, 없으면 fetch.
  async function loadActiveSource() {
    lightboxOpen = false;
    const p = sources[activeIdx];
    if (!p) return;
    if (stash[p]) {
      restoreFromStash(p);
      return;
    }
    sourceLoading = true;
    sourceError = null;
    try {
      const [ds, st] = await Promise.all([getDataset(p, mapping), getState(p)]);
      applyDataset(ds, st);
    } catch (e) {
      sourceError = e?.message || String(e);
      items = [];
      pointsByKey = {};
      order = [];
      selected = [];
      cursor = 0;
      displaySelection = [];
    } finally {
      sourceLoading = false;
    }
  }

  async function switchSource(i) {
    if (i === activeIdx || i < 0 || i >= sources.length) return;
    stashCurrent();
    activeIdx = i;
    status = null;
    exportInfo = null;
    await loadActiveSource();
  }

  function removeSource(i) {
    if (sources.length <= 1) return; // 최소 1개 유지
    const removed = sources[i];
    delete stash[removed];
    const removingActive = i === activeIdx;
    const next = sources.filter((_, idx) => idx !== i);
    let newActive = activeIdx;
    if (i < activeIdx) newActive = activeIdx - 1;
    else if (i === activeIdx) newActive = Math.min(i, next.length - 1);
    sources = next;
    activeIdx = newActive;
    if (removingActive) {
      status = null;
      exportInfo = null;
      loadActiveSource(); // 새 활성 소스 로드(보존분 복원 or fetch)
    }
  }

  // mode: 'add'(새 탭으로 추가) | 'change'(단일 소스 교체). 단일 소스 진입은 'change'.
  async function openPicker(mode) {
    pickerMode = mode;
    pickerOpen = true;
    pickedPath = "";
    preview = null;
    previewError = null;
    catalogLoading = true;
    try {
      const res = await getSources(activePath || sources[0]);
      catalog = Array.isArray(res.sources) ? res.sources : [];
    } catch (e) {
      catalog = [];
      status = { kind: "err", text: `소스 목록 로드 실패: ${e?.message || e}` };
    } finally {
      catalogLoading = false;
    }
  }

  function closePicker() {
    pickerOpen = false;
    pickedPath = "";
    preview = null;
    previewError = null;
  }

  // 후보를 선택하면 head(10) 미리보기를 불러와 어떤 소스인지 판단하게 한다.
  async function pickCandidate(p) {
    pickedPath = p;
    preview = null;
    previewError = null;
    previewLoading = true;
    try {
      preview = await getPreview(p, 10);
    } catch (e) {
      previewError = e?.message || String(e);
    } finally {
      previewLoading = false;
    }
  }

  // 새 탭으로 추가.
  function addSource(p) {
    if (!p) return;
    if (sources.includes(p)) {
      switchSource(sources.indexOf(p));
      closePicker();
      return;
    }
    stashCurrent();
    sources = [...sources, p];
    activeIdx = sources.length - 1;
    closePicker();
    status = null;
    exportInfo = null;
    loadActiveSource();
  }

  // 활성(단일) 소스를 새 소스로 교체. 이전 소스의 작업상태는 폐기한다.
  function changeSource(p) {
    if (!p) return;
    if (sources.includes(p)) {
      switchSource(sources.indexOf(p));
      closePicker();
      return;
    }
    const old = sources[activeIdx];
    delete stash[old];
    sources = sources.map((s, i) => (i === activeIdx ? p : s));
    closePicker();
    status = null;
    exportInfo = null;
    loadActiveSource();
  }

  function moveCursor(delta) {
    if (order.length === 0) return;
    cursor = Math.max(0, Math.min(order.length - 1, cursor + delta));
    // 키보드 이동은 단일 표시로 전환(다중은 Ctrl+클릭 전용).
    displaySelection = [order[cursor]];
  }

  function toggleSelected(key) {
    selected = selected.includes(key)
      ? selected.filter((k) => k !== key)
      : [...selected, key];
    status = null;
  }

  // 항목 클릭 → 차트 표시. Ctrl/⌘+클릭이면 표시 집합에 토글, 아니면 단일 표시.
  function selectDisplay(index, key, e) {
    cursor = index;
    if (e && (e.ctrlKey || e.metaKey)) {
      displaySelection = displaySelection.includes(key)
        ? displaySelection.filter((k) => k !== key)
        : [...displaySelection, key];
    } else {
      displaySelection = [key];
    }
  }

  function moveItem(index, delta) {
    const j = index + delta;
    if (j < 0 || j >= order.length) return;
    const nextOrder = [...order];
    [nextOrder[index], nextOrder[j]] = [nextOrder[j], nextOrder[index]];
    order = nextOrder;
    if (cursor === index) cursor = j;
    else if (cursor === j) cursor = index;
    status = null;
  }

  function openLightbox(i) {
    lightboxIndex = i;
    lightboxOpen = true;
  }
  function closeLightbox() {
    lightboxOpen = false;
  }
  function lightboxNext() {
    if (displayCharts.length <= 1) return;
    lightboxIndex = (lightboxIndex + 1) % displayCharts.length;
  }
  function lightboxPrev() {
    if (displayCharts.length <= 1) return;
    lightboxIndex = (lightboxIndex - 1 + displayCharts.length) % displayCharts.length;
  }

  // ── 좌측 패널 리사이즈 ───────────────────────────────────────────
  function onSidebarResizeDown(e) {
    if (e.button !== 0) return;
    resizingSidebar = true;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    e.preventDefault();
  }
  function onSidebarResizeMove(e) {
    if (!resizingSidebar) return;
    // .body 좌측 경계 = 창 좌측(앱 전체폭)이므로 clientX 가 곧 사이드바 너비.
    const max = Math.min(640, window.innerWidth - 360);
    sidebarWidth = Math.max(220, Math.min(max, e.clientX));
  }
  function onSidebarResizeUp(e) {
    if (!resizingSidebar) return;
    resizingSidebar = false;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
  }

  // ── 저장 / 내보내기 ───────────────────────────────────────────────
  async function onSave() {
    saving = true;
    status = null;
    try {
      await saveState(activePath, selectedOrdered, order);
      status = { kind: "ok", text: "상태를 저장했습니다." };
    } catch (e) {
      status = { kind: "err", text: e?.message || String(e) };
    } finally {
      saving = false;
    }
  }

  // result/<session>/<ts>/file → <session> (내보내기 알림의 세션 상관키).
  function sessionFromPath(p) {
    const parts = String(p).split("/");
    const i = parts.indexOf("result");
    return i >= 0 && parts.length > i + 1 ? parts[i + 1] : "";
  }

  // 내보내기 산출물을 같은 출처(same-origin)인 메인 앱 탭에 알린다. 메인 앱이
  // 구독해 parquet 데이터 칩으로 사용자에게 인폼한다(BroadcastChannel 미지원 무시).
  function broadcastExport(info) {
    try {
      const ch = new BroadcastChannel("evaluator:exports");
      ch.postMessage(info);
      ch.close();
    } catch {
      // 구형 브라우저 등 미지원 환경 — 알림만 생략, 내보내기 자체는 성공.
    }
  }

  // 선택 항목별로 차트 Filter 제외 인덱스를 모은다 — 내보내기 시 실제 행 제거에 반영.
  function collectExclusions() {
    const excluded = {};
    for (const key of selectedOrdered) {
      const snap = currentSnapshot(`${activePath}::${key}`);
      if (snap?.excluded?.length) excluded[key] = [...snap.excluded];
    }
    return excluded;
  }

  async function onExport() {
    if (selectedOrdered.length === 0) {
      status = { kind: "err", text: "선택된 항목이 없습니다." };
      return;
    }
    exporting = true;
    status = null;
    try {
      const res = await exportCurated(
        activePath,
        selectedOrdered,
        mapping,
        collectExclusions(),
      );
      exportInfo = { path: res.path, rows: res.rows, items: res.items };
      status = { kind: "ok", text: "내보내기 완료" };
      broadcastExport({
        type: "export",
        session: sessionFromPath(res.path),
        path: res.path,
        filename: res.filename,
        rows: res.rows,
        columns: res.columns,
        at: Date.now(),
      });
    } catch (e) {
      status = { kind: "err", text: e?.message || String(e) };
    } finally {
      exporting = false;
    }
  }

  function handleKey(e) {
    if (lightboxOpen) return; // 라이트박스가 자체 키 처리
    if (pickerOpen && e.key === "Escape") {
      closePicker();
      return;
    }
    const tag = (e.target?.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea") return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      moveCursor(1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      moveCursor(-1);
    } else if (e.key === " ") {
      if (tag === "button") return; // 버튼 포커스 시 space 는 버튼 활성화에 양보
      e.preventDefault();
      const key = order[cursor];
      if (key) toggleSelected(key);
    }
  }
</script>

<svelte:window onkeydown={handleKey} />

<div class="app">
  <header class="topbar">
    <div class="brand">
      <span class="dot"></span>
      <strong>Evaluator</strong>
      <span class="sub">데이터 큐레이션</span>
    </div>
    {#if sources.length > 1}
      <button class="add-src" onclick={() => openPicker("add")} title="세션 산출물에서 소스 추가">
        + 소스 추가
      </button>
    {:else}
      <button class="add-src" onclick={() => openPicker("change")} title="세션 산출물에서 다른 소스로 변경">
        소스 변경
      </button>
    {/if}
    {#if activePath}
      <code class="path" title={activePath}>{activePath}</code>
    {/if}
  </header>

  {#if sources.length > 1}
    <div class="tabs" role="tablist">
      {#each sources as src, i (src)}
        <div class="tab" class:active={i === activeIdx}>
          <button class="tab-label" title={src} onclick={() => switchSource(i)}>
            {fileName(src)}
          </button>
          <button class="tab-x" title="소스 제거" onclick={() => removeSource(i)}>×</button>
        </div>
      {/each}
    </div>
  {/if}

  {#if loading}
    <div class="center muted">불러오는 중…</div>
  {:else if error}
    <div class="center">
      <div class="err-box">
        <strong>로드 실패</strong>
        <p>{error}</p>
        <p class="muted small">
          예: <code>/ext/evaluator/?path=result/&lt;session&gt;/&lt;ts&gt;/sample.parquet</code>
          또는 <code>?bundle=result/…/evaluator.bundle.json</code>
        </p>
      </div>
    </div>
  {:else}
    <div class="body" class:resizing-x={resizingSidebar}>
      {#if sourceLoading}
        <div class="center muted">소스 불러오는 중…</div>
      {:else if sourceError}
        <div class="center">
          <div class="err-box">
            <strong>소스 로드 실패</strong>
            <p>{sourceError}</p>
            <p class="muted small">탭을 제거하거나 다른 소스를 추가해 보세요.</p>
          </div>
        </div>
      {:else}
        <!-- 좌측: 선택 기준 리스트 (드래그로 너비 조절) -->
        <aside class="sidebar" style="width: {sidebarWidth}px">
          <div class="list-head">
            <span>선택 기준 ({mapping.select})</span>
            <span class="count">{selectedOrdered.length} / {items.length}</span>
          </div>
          <ul class="list">
            {#each order as key, index (key)}
              {@const item = items.find((i) => i.key === key)}
              <li
                class="row"
                class:active={index === cursor}
                class:displayed={displaySelection.includes(key)}
                class:checked={selected.includes(key)}
              >
                <div class="reorder">
                  <button class="mini" title="위로" disabled={index === 0} onclick={() => moveItem(index, -1)}>↑</button>
                  <button class="mini" title="아래로" disabled={index === order.length - 1} onclick={() => moveItem(index, 1)}>↓</button>
                </div>
                <input
                  type="checkbox"
                  checked={selected.includes(key)}
                  onchange={() => toggleSelected(key)}
                />
                <button class="meta" onclick={(e) => selectDisplay(index, key, e)} title="클릭: 차트 표시 · Ctrl/⌘+클릭: 여러 항목 동시 표시">
                  <div class="key-line">
                    <span class="rank">#{item?.sort ?? "–"}</span>
                    <span class="key">{key}</span>
                    {#if displaySelection.includes(key)}<span class="shown-dot" title="표시 중"></span>{/if}
                  </div>
                  {#if item?.desc}
                    <div class="desc">{item.desc}</div>
                  {/if}
                </button>
              </li>
            {/each}
          </ul>
          <p class="hint muted small">
            ↑/↓ 이동 · Space 선택 · 클릭 차트표시 · Ctrl+클릭 다중표시 · 행 ↑↓ 순서변경
          </p>
        </aside>

        <!-- 너비 조절 핸들 -->
        <div
          class="col-resizer"
          role="separator"
          aria-orientation="vertical"
          aria-label="좌측 패널 너비 조절"
          onpointerdown={onSidebarResizeDown}
          onpointermove={onSidebarResizeMove}
          onpointerup={onSidebarResizeUp}
          onpointercancel={onSidebarResizeUp}
        ></div>

        <!-- 본문: 표시 선택된 항목들의 차트 그리드 -->
        <main class="content">
          <ChartGrid charts={displayCharts} onopen={openLightbox} />
        </main>
      {/if}
    </div>

    <!-- 하단: 액션 -->
    <footer class="actions">
      <div class="status">
        {#if status}
          <span class={status.kind === "ok" ? "ok" : "err"}>{status.text}</span>
        {/if}
        {#if exportInfo}
          <code class="export-path" title={exportInfo.path}>
            → {exportInfo.path} ({exportInfo.items}개 · {exportInfo.rows}행)
          </code>
        {/if}
      </div>
      <div class="buttons">
        <button class="btn" onclick={onSave} disabled={saving}>
          {saving ? "저장 중…" : "저장하기"}
        </button>
        <button class="btn primary" onclick={onExport} disabled={exporting || selectedOrdered.length === 0}>
          {exporting ? "내보내는 중…" : "내보내기"}
        </button>
      </div>
    </footer>
  {/if}

  {#if lightboxOpen}
    <ChartLightbox
      charts={displayCharts}
      index={lightboxIndex}
      onclose={closeLightbox}
      onnext={lightboxNext}
      onprev={lightboxPrev}
    />
  {/if}

  {#if pickerOpen}
    {@const pickerTitle = pickerMode === "change" ? "소스 변경" : "소스 추가"}
    <div
      class="picker-backdrop"
      onclick={(e) => {
        if (e.target === e.currentTarget) closePicker();
      }}
      role="presentation"
    >
      <div class="picker" role="dialog" aria-label={pickerTitle}>
        <div class="picker-head">
          <strong>{pickerTitle}</strong>
          <button class="picker-close" onclick={closePicker} aria-label="닫기">×</button>
        </div>
        <div class="picker-main">
          <!-- 좌: 후보 리스트 -->
          <ul class="cat-list">
            {#if catalogLoading}
              <li class="muted small pad">불러오는 중…</li>
            {:else if catalog.length === 0}
              <li class="muted small pad">이 세션에서 발견된 parquet 후보가 없습니다.</li>
            {:else}
              {#each catalog as c (c.path)}
                {@const added = sources.includes(c.path)}
                <li>
                  <button
                    class="cat-row"
                    class:picked={c.path === pickedPath}
                    title={c.path}
                    onclick={() => pickCandidate(c.path)}
                  >
                    <span class="cat-name">{c.filename}</span>
                    <span class="cat-meta">
                      {#if c.rows != null}{c.rows}행{/if}
                      {#if added}· 사용 중{/if}
                    </span>
                  </button>
                </li>
              {/each}
            {/if}
          </ul>

          <!-- 우: 미리보기 + 액션 -->
          <div class="preview-pane">
            {#if !pickedPath}
              <div class="center muted small">왼쪽에서 소스를 선택하면 미리보기가 표시됩니다.</div>
            {:else if previewLoading}
              <div class="center muted small">미리보기 불러오는 중…</div>
            {:else if previewError}
              <div class="center">
                <div class="err-box">
                  <strong>미리보기 실패</strong>
                  <p class="small">{previewError}</p>
                </div>
              </div>
            {:else if preview}
              {@const added = sources.includes(pickedPath)}
              {@const isCurrent = pickedPath === activePath}
              <div class="pv-meta">
                <span class="pv-name" title={preview.path}>{preview.filename}</span>
                <span class="muted small">{preview.total_rows}행 × {preview.schema.length}열</span>
              </div>
              <div class="pv-table-scroll">
                <table class="pv-table">
                  <thead>
                    <tr>
                      {#each preview.head.columns as col, i (col)}
                        <th>
                          <div class="pv-col">{col}</div>
                          <div class="pv-dtype">{preview.schema[i]?.dtype ?? ""}</div>
                        </th>
                      {/each}
                    </tr>
                  </thead>
                  <tbody>
                    {#each preview.head.rows as row, ri (ri)}
                      <tr>
                        {#each row as cell, ci (ci)}
                          <td>
                            {#if cell === null}
                              <span class="pv-null">null</span>
                            {:else}
                              {cell}
                            {/if}
                          </td>
                        {/each}
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
              <div class="pv-actions">
                {#if pickerMode === "change"}
                  {#if isCurrent}
                    <span class="muted small">현재 소스입니다.</span>
                  {:else}
                    <button class="btn primary" onclick={() => changeSource(pickedPath)}>
                      {added ? "이 탭으로 전환" : "이 소스로 변경"}
                    </button>
                    {#if !added}
                      <button class="btn" onclick={() => addSource(pickedPath)}>새 탭으로 추가</button>
                    {/if}
                  {/if}
                {:else}
                  <button class="btn primary" onclick={() => addSource(pickedPath)}>
                    {added ? "이 탭으로 전환" : "추가"}
                  </button>
                {/if}
              </div>
            {/if}
          </div>
        </div>
      </div>
    </div>
  {/if}
</div>

<style>
  .app {
    display: flex;
    flex-direction: column;
    height: 100vh;
    overflow: hidden;
  }

  .topbar {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 10px 16px;
    background: var(--panel);
    border-bottom: 1px solid var(--border);
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .brand .dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--accent);
  }
  .brand .sub {
    color: var(--muted);
    font-size: 13px;
  }
  .add-src {
    margin-left: auto;
    padding: 5px 12px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--border);
    background: var(--panel);
    color: var(--fg);
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
  }
  .add-src:hover {
    background: var(--panel-2);
    border-color: var(--accent-border);
    color: var(--accent);
  }
  .path {
    max-width: 42%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--muted);
    font-size: 12px;
    background: var(--panel-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 3px 8px;
  }

  .tabs {
    flex-shrink: 0;
    display: flex;
    gap: 4px;
    padding: 6px 10px 0;
    background: var(--panel);
    border-bottom: 1px solid var(--border);
    overflow-x: auto;
  }
  .tab {
    display: flex;
    align-items: center;
    border: 1px solid var(--border);
    border-bottom: none;
    border-radius: var(--radius-sm) var(--radius-sm) 0 0;
    background: var(--panel-2);
    max-width: 220px;
  }
  .tab.active {
    background: var(--bg);
    border-color: var(--accent-border);
  }
  .tab-label {
    min-width: 0;
    padding: 7px 4px 7px 12px;
    border: none;
    background: transparent;
    color: var(--muted);
    font-size: 12px;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    cursor: pointer;
  }
  .tab.active .tab-label {
    color: var(--fg);
  }
  .tab-x {
    padding: 0 8px;
    border: none;
    background: transparent;
    color: var(--subtle);
    font-size: 15px;
    line-height: 1;
    cursor: pointer;
  }
  .tab-x:hover {
    color: var(--danger);
  }

  .body {
    flex: 1;
    display: flex;
    min-height: 0;
  }
  .body.resizing-x {
    cursor: col-resize;
    user-select: none;
  }

  .sidebar {
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    background: var(--panel);
    border-right: 1px solid var(--border);
    min-height: 0;
  }
  .col-resizer {
    flex-shrink: 0;
    width: 6px;
    margin: 0 -3px;
    cursor: col-resize;
    background: transparent;
    z-index: 5;
    touch-action: none;
  }
  .col-resizer:hover {
    background: var(--accent-soft-strong);
  }
  .list-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 14px;
    font-weight: 600;
    font-size: 13px;
    border-bottom: 1px solid var(--border);
  }
  .list-head .count {
    color: var(--accent);
    font-variant-numeric: tabular-nums;
  }
  .list {
    list-style: none;
    margin: 0;
    padding: 6px;
    overflow-y: auto;
    flex: 1;
  }
  .row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 10px;
    border-radius: var(--radius-sm);
    cursor: pointer;
    border: 1px solid transparent;
  }
  .row:hover {
    background: var(--panel-2);
  }
  .row.displayed {
    background: var(--accent-soft);
    border-color: var(--accent-border);
  }
  .row.active {
    border-color: var(--accent);
  }
  .row.checked .key {
    color: var(--accent);
  }
  .reorder {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .mini {
    width: 20px;
    height: 16px;
    line-height: 1;
    padding: 0;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--panel);
    color: var(--muted);
    font-size: 11px;
  }
  .mini:hover:not(:disabled) {
    border-color: var(--accent-border);
    color: var(--accent);
  }
  .mini:disabled {
    opacity: 0.35;
    cursor: default;
  }
  .row input[type="checkbox"] {
    width: 16px;
    height: 16px;
    accent-color: var(--accent);
    cursor: pointer;
  }
  .meta {
    min-width: 0;
    flex: 1;
    display: block;
    text-align: left;
    padding: 0;
    border: none;
    background: transparent;
    color: inherit;
    font: inherit;
    cursor: pointer;
  }
  .key-line {
    display: flex;
    align-items: baseline;
    gap: 8px;
  }
  .rank {
    font-size: 11px;
    color: var(--subtle);
    font-variant-numeric: tabular-nums;
  }
  .key {
    font-weight: 600;
  }
  .shown-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--accent);
    align-self: center;
  }
  .desc {
    font-size: 12px;
    color: var(--muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .hint {
    margin: 0;
    padding: 8px 12px;
    border-top: 1px solid var(--border);
  }

  .content {
    flex: 1;
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
    padding: 14px;
    background: var(--bg);
  }

  .actions {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 12px 16px;
    background: var(--panel);
    border-top: 1px solid var(--border);
  }
  .status {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 12px;
    font-size: 13px;
  }
  .status .ok {
    color: var(--success);
  }
  .status .err {
    color: var(--danger);
  }
  .export-path {
    color: var(--muted);
    font-size: 12px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .buttons {
    display: flex;
    gap: 10px;
  }
  .btn {
    padding: 8px 18px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--border);
    background: var(--panel);
    color: var(--fg);
    font-weight: 600;
  }
  .btn:hover:not(:disabled) {
    background: var(--panel-2);
  }
  .btn.primary {
    background: var(--accent);
    border-color: var(--accent);
    color: var(--accent-fg);
  }
  .btn.primary:hover:not(:disabled) {
    background: var(--accent-hover);
  }
  .btn:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .picker-backdrop {
    position: fixed;
    inset: 0;
    background: var(--backdrop, rgba(0, 0, 0, 0.45));
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 50;
  }
  .picker {
    width: 820px;
    max-width: 92vw;
    height: 70vh;
    max-height: 560px;
    display: flex;
    flex-direction: column;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: var(--radius-md, 12px);
    overflow: hidden;
  }
  .picker-head {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
    font-size: 14px;
  }
  .picker-close {
    border: none;
    background: transparent;
    color: var(--muted);
    font-size: 18px;
    line-height: 1;
    cursor: pointer;
  }
  .picker-main {
    flex: 1;
    display: flex;
    min-height: 0;
  }
  .pad {
    padding: 16px;
  }
  .cat-list {
    width: 260px;
    flex-shrink: 0;
    list-style: none;
    margin: 0;
    padding: 6px;
    overflow-y: auto;
    border-right: 1px solid var(--border);
  }
  .cat-row {
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 8px 10px;
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--fg);
    text-align: left;
    cursor: pointer;
  }
  .cat-row:hover {
    background: var(--panel-2);
  }
  .cat-row.picked {
    background: var(--accent-soft);
    border-color: var(--accent-border);
  }
  .cat-name {
    min-width: 0;
    font-size: 13px;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .cat-meta {
    font-size: 11px;
    color: var(--muted);
    font-variant-numeric: tabular-nums;
  }

  .preview-pane {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    padding: 12px 14px;
    gap: 8px;
  }
  .pv-meta {
    flex-shrink: 0;
    display: flex;
    align-items: baseline;
    gap: 10px;
  }
  .pv-name {
    min-width: 0;
    font-size: 13px;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .pv-table-scroll {
    flex: 1;
    overflow: auto;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    min-height: 0;
  }
  .pv-table {
    border-collapse: collapse;
    font-size: 12px;
    width: max-content;
    min-width: 100%;
  }
  .pv-table th,
  .pv-table td {
    border-bottom: 1px solid var(--border);
    padding: 5px 10px;
    text-align: left;
    white-space: nowrap;
    max-width: 220px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .pv-table th {
    position: sticky;
    top: 0;
    background: var(--panel-2);
    z-index: 1;
  }
  .pv-col {
    font-weight: 600;
  }
  .pv-dtype {
    font-size: 10px;
    font-weight: 400;
    color: var(--muted);
    font-family: ui-monospace, "SFMono-Regular", Menlo, monospace;
  }
  .pv-table td {
    font-family: ui-monospace, "SFMono-Regular", Menlo, monospace;
    color: var(--fg);
  }
  .pv-null {
    color: var(--subtle);
    font-style: italic;
  }
  .pv-actions {
    flex-shrink: 0;
    display: flex;
    gap: 10px;
    align-items: center;
    padding-top: 2px;
  }

  .center {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 32px;
  }
  .muted {
    color: var(--muted);
  }
  .small {
    font-size: 12px;
  }
  .err-box {
    max-width: 460px;
    text-align: center;
  }
  .err-box p {
    margin: 8px 0 0;
  }
  code {
    font-family: ui-monospace, "SFMono-Regular", Menlo, monospace;
  }
</style>
