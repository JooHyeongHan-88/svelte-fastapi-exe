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
  import ChartCell from "./lib/ChartCell.svelte";
  import ChartLightbox from "./lib/ChartLightbox.svelte";
  import { currentSnapshot } from "./lib/chartState.svelte.js";
  import {
    MARKS,
    MARK_BY_ID,
    AGGREGATES,
    flattenForOverview,
  } from "./lib/chartOption.js";

  // 단일 컬럼 역할(legend 만 다중). readUrl·normalizeMapping 이 공유.
  const SINGLE_ROLE_KEYS = ["select", "sort", "x", "y", "desc"];

  // 매핑 역할별 라벨·설명(매핑 UI 노출). SKILLS/rank_review.md 의 매핑 계약과 동일.
  const ROLE_INFO = {
    select: {
      label: "선택 기준",
      desc: "좌측 리스트 항목의 고유 키 — 검토·선별·내보내기의 행 단위",
      multi: false,
    },
    sort: {
      label: "Sort 기준",
      desc: "리스트 정렬·내보내기 순위 재계산 기준(정수)",
      multi: false,
    },
    legend: {
      label: "레전드",
      desc: "시리즈 그룹(범례). 여러 컬럼을 고르면 합성 그룹이 됩니다.",
      multi: true,
    },
    desc: {
      label: "설명",
      desc: "리스트에 보조 표시할 설명 (선택 — 없어도 됨)",
      multi: false,
    },
    x: { label: "X축", desc: "차트 가로축 값", multi: false },
    y: { label: "Y축", desc: "차트 세로축 값", multi: false },
  };
  const COMMON_ROLES = ["select", "sort", "legend", "desc"]; // 차트 무관 공통 역할

  let mapping = $state({}); // 활성 소스의 컬럼 역할 매핑(legend 는 배열)
  let mark = $state("scatter"); // 활성 소스의 차트 종류
  let viewMode = $state("per-item"); // "per-item"(항목별 그리드) | "overview"(전체 조망)
  let aggregate = $state("mean"); // bar 집계 함수
  let schema = $state([]); // 활성 소스 스키마 [{name, dtype}] — 매핑 드롭다운용
  let bundleMapping = $state({}); // 번들/쿼리 기본 매핑(사이드카 없을 때 시드)
  let bundleMark = $state(""); // 번들 기본 차트 종류
  let loading = $state(true); // 초기 전체 로드
  let error = $state(null); // 치명적 에러 (번들 실패 등)
  let landing = $state(false); // 소스/번들 없이 열림 — 랜딩 페이지(소스 경로 입력 안내)
  let landingPath = $state(""); // 랜딩에서 사용자가 입력한 parquet 경로

  let sources = $state([]); // 작업 세트: 소스 경로 배열
  let activeIdx = $state(0);

  // 활성 소스의 작업 상태 (탭 전환 시 stash 에서 복원).
  let items = $state([]); // [{key, sort, desc}]
  let pointsByKey = $state({}); // key -> [{x,y,legend}]
  let order = $state([]); // 표시 순서의 키 배열
  let selected = $state([]); // 체크된 키(order 의 부분집합 — 내보내기 대상)
  let cursor = $state(0); // 키보드 하이라이트 — filteredOrder(가시 리스트) 기준 인덱스
  let displaySelection = $state([]); // 차트로 표시 중인 키 집합(Ctrl+클릭 다중 선택)
  let sourceLoading = $state(false); // 탭 전환 시 활성 소스 로딩
  let sourceError = $state(null); // 활성 소스 로드 실패 (탭 단위)

  // 리스트 검색·필터(휘발성 뷰 상태 — 표시만 좁힘, 순서/내보내기 의미 불변).
  let listQuery = $state(""); // key·desc 부분일치 검색
  let legendFilter = $state(""); // legend 값으로 좁히기(빈=전체)

  // 매핑/차트 설정 모달의 드래프트 상태.
  let mappingModalOpen = $state(false);
  let draftMark = $state("scatter");
  let draftMapping = $state({});
  let draftAgg = $state("mean");

  let saving = $state(false);
  let exporting = $state(false);
  let status = $state(null); // {kind: "ok"|"err", text}
  let exportInfo = $state(null); // {path, rows, items}
  let note = $state(""); // 내보내기 메모 — 요약 환류에 동봉(사람의 결정 맥락)

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
  // 키 → 전체 order 내 위치 — 순서 이동 버튼 disabled 판정(필터 무관).
  let orderIndex = $derived.by(() => {
    const m = {};
    order.forEach((k, i) => (m[k] = i));
    return m;
  });

  // 키별 legend 값 집합 — 리스트 legend 필터·드롭다운 카탈로그의 단일 원천.
  let legendByKey = $derived.by(() => {
    const map = {};
    for (const [k, pts] of Object.entries(pointsByKey)) {
      const set = new Set();
      for (const p of pts) {
        if (p.legend != null && p.legend !== "") set.add(String(p.legend));
      }
      map[k] = set;
    }
    return map;
  });
  let legendValues = $derived.by(() => {
    const set = new Set();
    for (const s of Object.values(legendByKey)) for (const v of s) set.add(v);
    return [...set].sort();
  });

  // 검색·legend 필터를 적용한 가시 순서. 비필터 시 order 그대로(참조 동일).
  let filteredOrder = $derived.by(() => {
    const q = listQuery.trim().toLowerCase();
    const lf = legendFilter;
    if (!q && !lf) return order;
    return order.filter((k) => {
      if (lf && !legendByKey[k]?.has(lf)) return false;
      if (q) {
        const item = items.find((i) => i.key === k);
        if (!`${k} ${item?.desc ?? ""}`.toLowerCase().includes(q)) return false;
      }
      return true;
    });
  });
  // 가시 집합 중 체크된 수 — 일괄 버튼 상태 표시용.
  let visibleSelectedCount = $derived(
    filteredOrder.filter((k) => selected.includes(k)).length,
  );

  // 필터가 좁혀져 cursor 가 범위를 벗어나면 클램프. legend 필터값이 사라지면 초기화.
  $effect(() => {
    if (cursor >= filteredOrder.length) {
      cursor = Math.max(0, filteredOrder.length - 1);
    }
  });
  $effect(() => {
    if (legendFilter && !legendValues.includes(legendFilter)) legendFilter = "";
  });

  // 매핑된 legend 컬럼(배열) · 차트 빌더에 넘길 역할 가용성 · 드롭다운 컬럼 목록.
  let legendCols = $derived(
    Array.isArray(mapping.legend)
      ? mapping.legend.filter(Boolean)
      : mapping.legend
        ? [mapping.legend]
        : [],
  );
  let roles = $derived({
    x: !!mapping.x,
    y: !!mapping.y,
    legend: legendCols.length > 0,
  });
  let columnNames = $derived(schema.map((s) => s.name));
  let markMeta = $derived(MARK_BY_ID[mark] ?? MARK_BY_ID.scatter);

  // 전체 조망 — 가시(필터된) 항목 전체를 한 차트에 모은다(항목=시리즈). 리스트 필터가
  // 곧 조망 범위가 되도록 filteredOrder 를 쓴다. legend 는 키로 강제하므로 항상 true.
  let overviewRoles = $derived({ x: !!mapping.x, y: !!mapping.y, legend: true });
  let overviewPoints = $derived(flattenForOverview(pointsByKey, filteredOrder));

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

  // legend 를 항상 배열로 정규화한다(쿼리/번들/사이드카가 문자열로 줄 수 있음).
  function normalizeMapping(m) {
    const out = { ...(m ?? {}) };
    if (out.legend == null) out.legend = [];
    else if (typeof out.legend === "string")
      out.legend = out.legend ? [out.legend] : [];
    else if (!Array.isArray(out.legend)) out.legend = [];
    else out.legend = out.legend.filter(Boolean);
    return out;
  }

  // 두 매핑의 '컬럼 역할'만 비교한다(mark·aggregate 제외) — 데이터 재요청 필요 판정용.
  function sameMappingColumns(a, b) {
    for (const k of SINGLE_ROLE_KEYS) {
      if ((a[k] ?? "") !== (b[k] ?? "")) return false;
    }
    const la = Array.isArray(a.legend) ? a.legend : [];
    const lb = Array.isArray(b.legend) ? b.legend : [];
    return la.length === lb.length && la.every((c, i) => c === lb[i]);
  }

  function readUrl() {
    const q = new URLSearchParams(window.location.search);
    const m = {};
    for (const k of SINGLE_ROLE_KEYS) {
      const v = q.get(k);
      if (v) m[k] = v;
    }
    const legendAll = q.getAll("legend").filter(Boolean);
    if (legendAll.length) m.legend = legendAll;
    return {
      path: q.get("path") || "",
      bundle: q.get("bundle") || "",
      queryMapping: m,
    };
  }

  // 번들(open_curation 산출)을 읽어 소스 목록·매핑·차트 종류를 확정한다. 번들은
  // result/... 경로이며 호스트가 /result/ 로 서빙한다.
  async function fetchBundle(bundle) {
    const res = await fetch(encodeURI("/" + bundle), { cache: "no-cache" });
    if (!res.ok) throw new Error(`번들 로드 실패: HTTP ${res.status}`);
    const b = await res.json();
    const list = Array.isArray(b.sources) ? b.sources : [];
    if (list.length === 0) throw new Error("번들에 sources 가 없습니다.");
    const m = b.mapping && typeof b.mapping === "object" ? b.mapping : {};
    const bmark = typeof b.mark === "string" ? b.mark : "";
    return { sources: list, mapping: m, mark: bmark };
  }

  async function loadAll() {
    loading = true;
    error = null;
    try {
      const { path, bundle, queryMapping } = readUrl();
      let initial = [];
      let seedMapping = queryMapping;
      let seedMark = "";
      if (bundle) {
        const b = await fetchBundle(bundle);
        initial = b.sources;
        seedMapping = { ...queryMapping, ...b.mapping };
        seedMark = b.mark || "";
      } else if (path) {
        initial = [path];
      }
      if (initial.length === 0) {
        // 소스/번들 없이 직접 열림(패널 런처 등) — 에러 대신 랜딩 페이지를 띄워
        // 소스 데이터·매핑 입력을 안내한다.
        landing = true;
        return;
      }
      bundleMapping = normalizeMapping(seedMapping);
      bundleMark = MARK_BY_ID[seedMark] ? seedMark : "";
      mapping = bundleMapping; // loadActiveSource 가 사이드카로 덮어쓸 수 있음
      sources = initial;
      activeIdx = 0;
      await loadActiveSource();
    } catch (e) {
      error = e?.message || String(e);
    } finally {
      loading = false;
    }
  }

  // 랜딩 페이지에서 사용자가 입력한 경로로 단일 소스를 적재한다(기본 매핑).
  // 로드 후 ⚙ 매핑 설정·소스 변경으로 컬럼 역할·소스를 보강할 수 있다.
  async function submitLanding() {
    const p = landingPath.trim();
    if (!p) return;
    landing = false;
    error = null;
    loading = false;
    bundleMapping = normalizeMapping({});
    bundleMark = "";
    mapping = bundleMapping;
    sources = [p];
    activeIdx = 0;
    await loadActiveSource();
  }

  onMount(loadAll);

  // 데이터셋 points 를 선택키별 묶음으로 변환한다.
  function pointsFromDataset(ds) {
    const pmap = {};
    for (const p of ds.points) {
      (pmap[p.key] ??= []).push({ x: p.x, y: p.y, legend: p.legend });
    }
    return pmap;
  }

  // 활성 소스 데이터/상태를 작업 변수에 반영한다(최초 로드·소스 교체용).
  function applyDataset(ds, st) {
    items = ds.items;
    mapping = normalizeMapping(ds.mapping); // 백엔드가 확정한 실제 매핑(기본값 채움)
    schema = Array.isArray(ds.schema) ? ds.schema : [];
    pointsByKey = pointsFromDataset(ds);

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
      mapping,
      mark,
      aggregate,
      schema,
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
    mapping = s.mapping;
    mark = s.mark;
    aggregate = s.aggregate;
    schema = s.schema ?? [];
    sourceError = null;
  }

  // 활성 소스(sources[activeIdx])를 작업 상태로 적재 — stash 우선, 없으면 fetch.
  // 사이드카(상태)에 저장된 매핑·차트 종류가 있으면 그것으로, 없으면 번들 기본값으로
  // 데이터셋을 요청한다(매핑이 데이터 투영을 바꾸므로 상태를 먼저 읽는다).
  async function loadActiveSource() {
    lightboxOpen = false;
    listQuery = "";
    legendFilter = "";
    const p = sources[activeIdx];
    if (!p) return;
    if (stash[p]) {
      restoreFromStash(p);
      return;
    }
    sourceLoading = true;
    sourceError = null;
    try {
      const st = await getState(p);
      const savedMapping =
        st.mapping && Object.keys(st.mapping).length
          ? normalizeMapping(st.mapping)
          : null;
      const effMapping = savedMapping ?? bundleMapping;
      const effMark = st.mark || bundleMark || "scatter";
      const ds = await getDataset(p, effMapping);
      mark = MARK_BY_ID[effMark] ? effMark : "scatter";
      aggregate = (savedMapping && savedMapping.aggregate) || "mean";
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

  // ── 차트 종류 · 매핑 설정 ─────────────────────────────────────────
  // 차트 종류 전환 — 데이터는 동일하므로 재요청 없이 재렌더만(roles 가 필요 컬럼 안내).
  function setMark(id) {
    if (MARK_BY_ID[id]) mark = id;
  }

  function openMappingModal() {
    draftMark = mark;
    draftMapping = {
      select: mapping.select || "",
      sort: mapping.sort || "",
      x: mapping.x || "",
      y: mapping.y || "",
      desc: mapping.desc || "",
      legend: [...legendCols],
    };
    draftAgg = aggregate;
    mappingModalOpen = true;
  }

  function closeMappingModal() {
    mappingModalOpen = false;
  }

  function setDraftRole(role, value) {
    draftMapping = { ...draftMapping, [role]: value };
  }

  // legend 다중 토글 — 선택 순서가 곧 합성 순서.
  function toggleDraftLegend(col) {
    const cur = Array.isArray(draftMapping.legend) ? draftMapping.legend : [];
    const next = cur.includes(col)
      ? cur.filter((c) => c !== col)
      : [...cur, col];
    draftMapping = { ...draftMapping, legend: next };
  }

  // 매핑/차트 설정 적용 — 컬럼 역할이 바뀌면 재요청(선택 보존), mark/집계만 바뀌면 재렌더.
  async function applyMappingConfig() {
    const norm = normalizeMapping(draftMapping);
    mark = MARK_BY_ID[draftMark] ? draftMark : mark;
    aggregate = draftAgg || "mean";
    mappingModalOpen = false;

    if (sameMappingColumns(norm, mapping)) {
      mapping = norm; // legend 정규화 차이만 반영
      return;
    }

    sourceLoading = true;
    sourceError = null;
    const prevSelected = [...selected];
    const prevOrder = [...order];
    const prevDisplay = [...displaySelection];
    const prevKeys = new Set(items.map((i) => i.key));
    try {
      const ds = await getDataset(activePath, norm);
      mapping = normalizeMapping(ds.mapping);
      schema = Array.isArray(ds.schema) ? ds.schema : schema;
      items = ds.items;
      pointsByKey = pointsFromDataset(ds);

      const itemKeys = items.map((i) => i.key);
      const sameKeys =
        itemKeys.length === prevKeys.size &&
        itemKeys.every((k) => prevKeys.has(k));
      if (sameKeys) {
        // 선택키 집합이 그대로면 사용자의 큐레이션 선택·순서를 보존한다.
        order = prevOrder.filter((k) => itemKeys.includes(k));
        for (const k of itemKeys) if (!order.includes(k)) order.push(k);
        selected = prevSelected.filter((k) => itemKeys.includes(k));
        displaySelection = prevDisplay.filter((k) => itemKeys.includes(k));
        if (displaySelection.length === 0 && order.length) {
          displaySelection = [order[0]];
        }
        cursor = Math.min(cursor, Math.max(0, order.length - 1));
      } else {
        // select 컬럼 변경 등으로 키가 바뀌면 새로 시작(전부 선택).
        order = itemKeys;
        selected = [...itemKeys];
        displaySelection = itemKeys.length ? [order[0]] : [];
        cursor = 0;
      }
    } catch (e) {
      sourceError = e?.message || String(e);
    } finally {
      sourceLoading = false;
    }
  }

  // 저장/내보내기에 실을 매핑(컬럼 역할 + bar 집계함수).
  function mappingForSave() {
    return { ...mapping, aggregate };
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
    if (filteredOrder.length === 0) return;
    cursor = Math.max(0, Math.min(filteredOrder.length - 1, cursor + delta));
    // 키보드 이동은 단일 표시로 전환(다중은 Ctrl+클릭 전용).
    displaySelection = [filteredOrder[cursor]];
  }

  function toggleSelected(key) {
    selected = selected.includes(key)
      ? selected.filter((k) => k !== key)
      : [...selected, key];
    status = null;
  }

  // ── 일괄 선택 (현재 가시 집합 filteredOrder 대상) ────────────────────
  function selectAllFiltered() {
    const set = new Set(selected);
    for (const k of filteredOrder) set.add(k);
    selected = [...set];
    status = null;
  }
  function clearAllFiltered() {
    const remove = new Set(filteredOrder);
    selected = selected.filter((k) => !remove.has(k));
    status = null;
  }
  function invertFiltered() {
    const set = new Set(selected);
    for (const k of filteredOrder) {
      if (set.has(k)) set.delete(k);
      else set.add(k);
    }
    selected = [...set];
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

  // 순서 이동은 항상 전체 order 기준(필터는 표시만 좁힘) — 키로 위치를 찾아 인접 교환.
  function moveItem(key, delta) {
    const index = order.indexOf(key);
    if (index < 0) return;
    const j = index + delta;
    if (j < 0 || j >= order.length) return;
    const nextOrder = [...order];
    [nextOrder[index], nextOrder[j]] = [nextOrder[j], nextOrder[index]];
    order = nextOrder;
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
      await saveState(activePath, selectedOrdered, order, mark, mappingForSave());
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
        note.trim(),
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
        summary: res.summary ?? null, // 사람의 결정 요약(메인 앱 칩에 표시)
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
      const key = filteredOrder[cursor];
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
  {:else if landing}
    <div class="center">
      <div class="landing-box">
        <span class="landing-dot"></span>
        <h2>큐레이션할 소스 데이터가 필요합니다</h2>
        <p class="muted">
          Evaluator 는 AI 가 만든 <strong>parquet 후보 데이터</strong>를 사람이 시각적으로
          검토·선별하는 도구입니다. 보통은 채팅에서 에이전트가 큐레이션 핸드오프
          (<code>open_curation</code>)로 소스와 컬럼 매핑을 함께 넘겨 열립니다.
        </p>
        <p class="muted">
          직접 검토하려면 아래에 <code>result/…</code> parquet 경로를 입력하세요.
          불러온 뒤 <strong>⚙ 매핑 설정</strong>에서 컬럼 역할(선택·정렬·축·레전드)을
          맞추고, <strong>소스 변경/추가</strong>로 다른 후보도 가져올 수 있습니다.
        </p>
        <form
          class="landing-form"
          onsubmit={(e) => {
            e.preventDefault();
            submitLanding();
          }}
        >
          <input
            class="landing-input"
            type="text"
            bind:value={landingPath}
            placeholder="result/<session>/<ts>/candidates.parquet"
            aria-label="parquet 경로"
          />
          <button class="landing-load" type="submit" disabled={!landingPath.trim()}>
            불러오기
          </button>
        </form>
      </div>
    </div>
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
          <div class="list-filter">
            <input
              class="search"
              type="text"
              bind:value={listQuery}
              placeholder="검색 (키·설명)"
              aria-label="리스트 검색"
            />
            {#if legendValues.length > 0}
              <select class="legend-filter" bind:value={legendFilter} title="레전드로 좁히기">
                <option value="">전체 레전드</option>
                {#each legendValues as lv (lv)}
                  <option value={lv}>{lv}</option>
                {/each}
              </select>
            {/if}
          </div>
          <div class="bulk-bar">
            <span class="bulk-count">
              {#if filteredOrder.length !== items.length}{filteredOrder.length}개 표시 · {/if}{visibleSelectedCount}개 선택
            </span>
            <div class="bulk">
              <button class="mini-btn" onclick={selectAllFiltered} title="표시된 항목 전체 선택">전체</button>
              <button class="mini-btn" onclick={clearAllFiltered} title="표시된 항목 선택 해제">해제</button>
              <button class="mini-btn" onclick={invertFiltered} title="표시된 항목 선택 반전">반전</button>
            </div>
          </div>
          <ul class="list">
            {#if filteredOrder.length === 0}
              <li class="empty-row muted small">조건에 맞는 항목이 없습니다.</li>
            {/if}
            {#each filteredOrder as key, index (key)}
              {@const item = items.find((i) => i.key === key)}
              <li
                class="row"
                class:active={index === cursor}
                class:displayed={displaySelection.includes(key)}
                class:checked={selected.includes(key)}
              >
                <div class="reorder">
                  <button class="mini" title="위로" disabled={orderIndex[key] === 0} onclick={() => moveItem(key, -1)}>↑</button>
                  <button class="mini" title="아래로" disabled={orderIndex[key] === order.length - 1} onclick={() => moveItem(key, 1)}>↓</button>
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

        <!-- 본문: 차트 종류 셀렉터 + 매핑 설정 + 차트 그리드 -->
        <main class="content">
          <div class="config-bar">
            <div class="mark-picker" role="group" aria-label="보기 모드">
              <button class="mark-btn" class:active={viewMode === "per-item"} onclick={() => (viewMode = "per-item")} title="선택 항목을 항목별 차트 그리드로">
                항목별
              </button>
              <button class="mark-btn" class:active={viewMode === "overview"} onclick={() => (viewMode = "overview")} title="가시 항목 전체를 한 차트에 모아 비교">
                전체 조망
              </button>
            </div>
            <div class="mark-picker" role="group" aria-label="차트 종류">
              {#each MARKS as m (m.id)}
                <button
                  class="mark-btn"
                  class:active={mark === m.id}
                  onclick={() => setMark(m.id)}
                  title={m.label}
                >
                  {m.label}
                </button>
              {/each}
            </div>
            <button class="map-btn" onclick={openMappingModal} title="컬럼 매핑·차트 설정">
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="2" /><path d="M8 1v2M8 13v2M1 8h2M13 8h2M3 3l1.5 1.5M11.5 11.5 13 13M13 3l-1.5 1.5M4.5 11.5 3 13" /></svg>
              매핑 설정
            </button>
          </div>
          {#if viewMode === "overview"}
            <div class="overview-wrap">
              {#if overviewPoints.length === 0}
                <div class="center muted small">표시할 항목이 없습니다 — 리스트 필터를 해제하거나 항목을 선택하세요.</div>
              {:else}
                <ChartCell
                  chartKey={`${activePath}::__overview__`}
                  points={overviewPoints}
                  {mark}
                  roles={overviewRoles}
                  {aggregate}
                  xName={mapping.x}
                  yName={mapping.y}
                  embedded={false}
                />
              {/if}
            </div>
          {:else}
            <ChartGrid
              charts={displayCharts}
              {mark}
              {roles}
              {aggregate}
              onopen={openLightbox}
            />
          {/if}
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
      <input
        class="note-input"
        type="text"
        bind:value={note}
        placeholder="큐레이션 메모 (선택) — 내보내기 시 채팅에 함께 전달"
        title="이 큐레이션의 결정 맥락을 한 줄로 남기면 메인 앱 칩 요약에 표시됩니다."
      />
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
      {mark}
      {roles}
      {aggregate}
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

  {#if mappingModalOpen}
    {@const meta = MARK_BY_ID[draftMark] ?? MARK_BY_ID.scatter}
    <div
      class="picker-backdrop"
      onclick={(e) => {
        if (e.target === e.currentTarget) closeMappingModal();
      }}
      role="presentation"
    >
      <div class="map-modal" role="dialog" aria-label="매핑 설정">
        <div class="picker-head">
          <strong>매핑 / 차트 설정</strong>
          <button class="picker-close" onclick={closeMappingModal} aria-label="닫기">×</button>
        </div>

        <div class="map-body">
          <!-- 차트 종류 -->
          <section class="map-section">
            <div class="map-section-title">차트 종류</div>
            <div class="mark-picker wrap" role="group" aria-label="차트 종류">
              {#each MARKS as m (m.id)}
                <button
                  class="mark-btn"
                  class:active={draftMark === m.id}
                  onclick={() => (draftMark = m.id)}
                >
                  {m.label}
                </button>
              {/each}
            </div>
          </section>

          {#if columnNames.length === 0}
            <p class="muted small">소스 스키마를 불러오지 못해 컬럼 목록이 비었습니다.</p>
          {/if}

          <!-- 공통 매핑 (차트 종류 무관) -->
          <section class="map-section">
            <div class="map-section-title">공통 매핑 <span class="muted small">— 모든 차트 공통</span></div>
            {#each COMMON_ROLES as role (role)}
              {@const info = ROLE_INFO[role]}
              <div class="map-row">
                <div class="map-role">
                  <span class="role-name">{info.label}</span>
                  <code class="role-key">{role}</code>
                  <p class="role-desc">{info.desc}</p>
                </div>
                <div class="map-control">
                  {#if info.multi}
                    <div class="chip-row">
                      {#each columnNames as col (col)}
                        <button
                          class="chip"
                          class:on={(draftMapping.legend ?? []).includes(col)}
                          onclick={() => toggleDraftLegend(col)}
                          title={col}
                        >
                          {col}
                        </button>
                      {/each}
                    </div>
                    {#if (draftMapping.legend ?? []).length}
                      <div class="chip-hint">합성: <strong>{draftMapping.legend.join(" | ")}</strong></div>
                    {:else}
                      <div class="chip-hint muted">선택 안 함 (그룹 없는 단일 시리즈)</div>
                    {/if}
                    {#if meta.usesLegend === false}
                      <div class="chip-hint muted">{meta.label}에서는 미사용(색=빈도) — 선택해 두면 다른 차트 종류에서 적용됩니다.</div>
                    {/if}
                  {:else}
                    <select
                      class="col-select"
                      value={draftMapping[role] ?? ""}
                      onchange={(e) => setDraftRole(role, e.currentTarget.value)}
                    >
                      {#if role === "desc"}<option value="">(없음)</option>{/if}
                      {#each columnNames as col (col)}
                        <option value={col}>{col}</option>
                      {/each}
                    </select>
                  {/if}
                </div>
              </div>
            {/each}
          </section>

          <!-- 차트별 매핑 (mark 에 따라 가변) -->
          <section class="map-section">
            <div class="map-section-title">
              차트 매핑 <span class="muted small">— {meta.label}</span>
            </div>
            {#if meta.needs.length === 0 && !meta.aggregate}
              <p class="muted small">이 차트 종류는 추가 컬럼 매핑이 필요 없습니다.</p>
            {/if}
            {#each meta.needs as role (role)}
              {@const info = ROLE_INFO[role]}
              <div class="map-row">
                <div class="map-role">
                  <span class="role-name">{info.label}</span>
                  <code class="role-key">{role}</code>
                  <p class="role-desc">{info.desc}</p>
                </div>
                <div class="map-control">
                  <select
                    class="col-select"
                    value={draftMapping[role] ?? ""}
                    onchange={(e) => setDraftRole(role, e.currentTarget.value)}
                  >
                    <option value="">(선택)</option>
                    {#each columnNames as col (col)}
                      <option value={col}>{col}</option>
                    {/each}
                  </select>
                </div>
              </div>
            {/each}
            {#if meta.aggregate}
              <div class="map-row">
                <div class="map-role">
                  <span class="role-name">집계</span>
                  <code class="role-key">aggregate</code>
                  <p class="role-desc">같은 X 값에 여러 행이 있으면 묶어서 집계합니다.</p>
                </div>
                <div class="map-control">
                  <select class="col-select" value={draftAgg} onchange={(e) => (draftAgg = e.currentTarget.value)}>
                    {#each AGGREGATES as a (a.id)}
                      <option value={a.id}>{a.label}</option>
                    {/each}
                  </select>
                </div>
              </div>
            {/if}
          </section>
        </div>

        <div class="map-foot">
          <button class="btn" onclick={closeMappingModal}>취소</button>
          <button class="btn primary" onclick={applyMappingConfig}>적용</button>
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
  .list-filter {
    display: flex;
    gap: 6px;
    padding: 8px 10px 0;
  }
  .search,
  .legend-filter {
    padding: 5px 8px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--bg);
    color: var(--fg);
    font-size: 12px;
  }
  .search {
    flex: 1;
    min-width: 0;
  }
  .search::placeholder {
    color: var(--subtle);
  }
  .search:focus,
  .legend-filter:focus {
    outline: none;
    border-color: var(--accent-border);
  }
  .legend-filter {
    flex-shrink: 0;
    max-width: 42%;
  }
  .bulk-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 8px 12px 6px;
  }
  .bulk-count {
    font-size: 11px;
    color: var(--muted);
    font-variant-numeric: tabular-nums;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .bulk {
    display: flex;
    gap: 4px;
    flex-shrink: 0;
  }
  .mini-btn {
    padding: 3px 9px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--panel);
    color: var(--muted);
    font-size: 11px;
    font-weight: 600;
    cursor: pointer;
  }
  .mini-btn:hover {
    border-color: var(--accent-border);
    color: var(--accent);
  }
  .empty-row {
    padding: 16px 12px;
    text-align: center;
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
    gap: 10px;
  }

  /* 차트 종류 셀렉터 + 매핑 설정 바 (Tableau 의 Marks 카드 느낌). */
  .config-bar {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }

  /* 전체 조망 — 단일 차트가 본문 전체를 채운다. */
  .overview-wrap {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    overflow: hidden;
  }
  .mark-picker {
    display: inline-flex;
    gap: 2px;
    padding: 2px;
    background: var(--panel-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
  }
  .mark-picker.wrap {
    flex-wrap: wrap;
  }
  .mark-btn {
    padding: 5px 11px;
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--muted);
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    white-space: nowrap;
  }
  .mark-btn:hover {
    color: var(--fg);
  }
  .mark-btn.active {
    background: var(--accent);
    border-color: var(--accent);
    color: var(--accent-fg);
  }
  .map-btn {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--panel);
    color: var(--fg);
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
  }
  .map-btn:hover {
    background: var(--panel-2);
    border-color: var(--accent-border);
    color: var(--accent);
  }

  /* 매핑 설정 모달 */
  .map-modal {
    width: 640px;
    max-width: 94vw;
    max-height: 88vh;
    display: flex;
    flex-direction: column;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: var(--radius-md, 12px);
    overflow: hidden;
  }
  .map-body {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 6px 18px 14px;
  }
  .map-section {
    padding: 12px 0;
    border-bottom: 1px solid var(--border);
  }
  .map-section:last-child {
    border-bottom: none;
  }
  .map-section-title {
    font-size: 13px;
    font-weight: 700;
    color: var(--fg);
    margin-bottom: 10px;
  }
  .map-row {
    display: flex;
    align-items: flex-start;
    gap: 14px;
    padding: 8px 0;
  }
  .map-role {
    width: 200px;
    flex-shrink: 0;
  }
  .role-name {
    font-size: 13px;
    font-weight: 600;
    color: var(--fg);
  }
  .role-key {
    font-size: 11px;
    color: var(--muted);
    background: var(--panel-2);
    border-radius: 4px;
    padding: 1px 5px;
    margin-left: 6px;
    font-family: ui-monospace, "SFMono-Regular", Menlo, monospace;
  }
  .role-desc {
    margin: 4px 0 0;
    font-size: 11.5px;
    color: var(--muted);
    line-height: 1.4;
  }
  .map-control {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding-top: 2px;
  }
  .col-select {
    width: 100%;
    max-width: 280px;
    padding: 6px 8px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--bg);
    color: var(--fg);
    font-size: 12px;
  }
  .chip-row {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
  }
  .chip {
    padding: 4px 10px;
    border: 1px solid var(--border);
    border-radius: var(--radius-full, 999px);
    background: var(--bg);
    color: var(--muted);
    font-size: 11.5px;
    cursor: pointer;
    white-space: nowrap;
  }
  .chip:hover {
    border-color: var(--accent-border);
    color: var(--fg);
  }
  .chip.on {
    background: var(--accent);
    border-color: var(--accent);
    color: var(--accent-fg);
  }
  .chip-hint {
    font-size: 11px;
    color: var(--fg);
  }
  .chip-hint.muted {
    color: var(--muted);
  }
  .map-foot {
    flex-shrink: 0;
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    padding: 12px 18px;
    border-top: 1px solid var(--border);
    background: var(--panel);
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
  .note-input {
    flex-shrink: 0;
    width: 280px;
    max-width: 32vw;
    padding: 7px 10px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--bg);
    color: var(--fg);
    font-size: 12px;
  }
  .note-input::placeholder {
    color: var(--subtle);
  }
  .note-input:focus {
    outline: none;
    border-color: var(--accent-border);
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
  .landing-box {
    max-width: 520px;
    text-align: center;
    padding: 28px 30px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--panel);
  }
  .landing-dot {
    display: inline-block;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: var(--accent);
    margin-bottom: 12px;
  }
  .landing-box h2 {
    margin: 0 0 12px;
    font-size: 17px;
    color: var(--fg);
  }
  .landing-box p {
    margin: 0 0 12px;
    font-size: 13px;
    line-height: 1.55;
    text-align: left;
  }
  .landing-form {
    display: flex;
    gap: 8px;
    margin-top: 16px;
  }
  .landing-input {
    flex: 1;
    min-width: 0;
    padding: 8px 10px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--bg);
    color: var(--fg);
    font-size: 13px;
    font-family: ui-monospace, "SFMono-Regular", Menlo, monospace;
    outline: none;
  }
  .landing-input:focus {
    border-color: var(--accent-border);
  }
  .landing-load {
    flex-shrink: 0;
    padding: 8px 16px;
    border: 1px solid var(--accent);
    border-radius: var(--radius-sm);
    background: var(--accent);
    color: var(--accent-fg);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
  }
  .landing-load:hover:not(:disabled) {
    background: var(--accent-hover);
  }
  .landing-load:disabled {
    opacity: 0.5;
    cursor: default;
  }
  code {
    font-family: ui-monospace, "SFMono-Regular", Menlo, monospace;
  }
</style>
