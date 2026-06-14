// 선택 항목(선택키)별 차트 ECharts option 을 클라이언트에서 구성한다.
//
// 메인 앱의 display_chart 는 백엔드 render_spec_to_echarts + /api/chart/filter 파이프라인을
// 거치지만, evaluator 의 차트는 이미 클라이언트에 적재된 points 를 보고 큐레이션을 판단하는
// 휘발성 검토 도구다. 따라서 격리 원칙에 따라 메인 앱 파이프라인에 결합하지 않고 option 을
// 클라이언트에서 직접 만든다(필터·레전드도 클라이언트 상태).
//
// buildChartOption 은 mark(차트 종류)별 빌더로 분기한다. 메인 앱 display_chart 와 동일한
// 7종(scatter/line/bar/box/histogram/ecdf/heatmap)을 지원하며, 제외(brush Filter)·레전드
// (순서·색상·Hide) 스냅샷을 반영하고, brush 선택을 원본 point 인덱스로 되돌릴 row_ids 를
// 함께 돌려준다. legend 역할은 모든 차트의 공통 시리즈 그룹(범례)이다 — 단 heatmap 은 색이
// 셀 카운트를 인코딩하므로 legend 를 그룹으로 쓰지 않는다.

// ECharts 기본 팔레트 — 색상 오버라이드 전 스와치/시리즈 색의 기준(메인 앱과 동일).
export const ECHARTS_PALETTE = [
  "#5470c6", "#91cc75", "#fac858", "#ee6666", "#73c0de",
  "#3ba272", "#fc8452", "#9a60b4", "#ea7ccc",
];

const LEGEND_FALLBACK = "—";
const HISTOGRAM_BIN_COUNT = 10; // 메인 앱 chart_renderer 와 동일 고정값.

// 차트 종류 메타데이터 — 매핑 UI(차트별 역할 노출)와 빌더 분기가 공유하는 단일 진실원천.
//   needs:     차트별로 반드시 매핑돼야 하는 역할(공통 select/sort/legend/desc 외).
//   brushable: brush 점 선택으로 데이터 제외가 가능한가(점↔원본 행 1:1 대응 차트만).
//   aggregate: 같은 x 값을 묶는 집계 함수 선택이 필요한가(bar 전용).
//   usesLegend: legend 를 시리즈 그룹으로 쓰는가(heatmap 은 색=카운트라 false).
export const MARKS = [
  { id: "scatter", label: "산점도", needs: ["x", "y"], brushable: true, usesLegend: true },
  { id: "line", label: "선", needs: ["x", "y"], brushable: true, usesLegend: true },
  { id: "bar", label: "막대", needs: ["x", "y"], brushable: false, usesLegend: true, aggregate: true },
  { id: "box", label: "박스", needs: ["y"], brushable: false, usesLegend: true },
  { id: "histogram", label: "히스토그램", needs: ["x"], brushable: false, usesLegend: true },
  { id: "ecdf", label: "누적분포", needs: ["x"], brushable: true, usesLegend: true },
  { id: "heatmap", label: "히트맵", needs: ["x", "y"], brushable: false, usesLegend: false },
];

export const MARK_BY_ID = Object.fromEntries(MARKS.map((m) => [m.id, m]));

const ROLE_LABELS = { x: "X축", y: "Y축", legend: "레전드" };

/** 집계 함수 선택지(bar 전용). */
export const AGGREGATES = [
  { id: "mean", label: "평균" },
  { id: "sum", label: "합계" },
  { id: "count", label: "개수" },
  { id: "min", label: "최소" },
  { id: "max", label: "최대" },
];

/** 빈(초기) 뷰 스냅샷 — 제외 없음 · 레전드 오버라이드 없음. */
export function emptySnapshot() {
  return { excluded: [], legend: { order: null, colors: {}, hidden: [] } };
}

/**
 * 조망(overview) 뷰용 평탄화 — 여러 선택키의 points 를 이어 붙이되 각 point 의 legend 를
 * 그 키로 덮어써 '항목=시리즈' 로 한 차트에서 비교 가능하게 만든다. brush 환원(원본 행
 * 인덱스)은 조망에서 쓰지 않으므로 단순 평탄화만 한다(읽기전용 비교 뷰).
 *
 * @param {Record<string, Array<{x:any,y:any,legend:any}>>} pointsByKey
 * @param {string[]} keys  포함할 선택키(표시 순서)
 * @returns {Array<{x:any,y:any,legend:string}>}
 */
export function flattenForOverview(pointsByKey, keys) {
  const out = [];
  for (const key of keys ?? []) {
    const pts = pointsByKey?.[key] ?? [];
    for (const p of pts) out.push({ x: p.x, y: p.y, legend: key });
  }
  return out;
}

/**
 * x 값 표본으로 ECharts 축 타입을 추정한다 — 도메인 비특정(숫자·날짜·범주) 대응.
 *
 * @param {Array<any>} values
 * @returns {"value"|"time"|"category"}
 */
function detectAxisType(values) {
  for (const v of values) {
    if (v === null || v === undefined) continue;
    if (typeof v === "number") return "value";
    if (typeof v === "string") {
      // 백엔드가 datetime 을 ISO 문자열로 내려보내므로 Date 파싱이 되면 time 축.
      return Number.isNaN(Date.parse(v)) ? "category" : "time";
    }
    return "category";
  }
  return "value";
}

/**
 * 레전드 표시 순서를 확정한다 — 오버라이드(order)에 있는 이름 우선, 새 이름은 자연 순서로 뒤에.
 *
 * @param {string[]} natural  데이터에서 등장한 순서
 * @param {string[]|null} override  사용자 지정 순서
 * @returns {string[]}
 */
function resolveLegendOrder(natural, override) {
  if (!Array.isArray(override) || override.length === 0) return natural;
  const present = new Set(natural);
  const ordered = override.filter((name) => present.has(name));
  const seen = new Set(ordered);
  for (const name of natural) {
    if (!seen.has(name)) ordered.push(name);
  }
  return ordered;
}

/**
 * points 를 레전드 이름별로 묶는다(제외 인덱스는 건너뜀). 각 원소는 원본 point 인덱스를 보존.
 *
 * @param {Array<{x:any,y:any,legend:any}>} points
 * @param {Set<number>} excluded
 * @param {boolean} grouped  legend 로 그룹할지(heatmap 은 false → 단일 그룹)
 * @returns {Map<string, Array<{x:any,y:any,idx:number}>>}
 */
function groupByLegend(points, excluded, grouped = true) {
  const groups = new Map();
  points.forEach((p, i) => {
    if (excluded.has(i)) return;
    const name = grouped ? (p.legend ?? LEGEND_FALLBACK) : LEGEND_FALLBACK;
    if (!groups.has(name)) groups.set(name, []);
    groups.get(name).push({ x: p.x, y: p.y, idx: i });
  });
  return groups;
}

/** 색상 오버라이드 적용한 시리즈 색을 고른다. */
function colorFor(name, idx, colors) {
  return colors[name] ?? ECHARTS_PALETTE[idx % ECHARTS_PALETTE.length];
}

/** legendNames → legend.selected({name:boolean}) (Hide 토글). */
function selectedMap(legendNames, hidden) {
  const selected = {};
  for (const name of legendNames) selected[name] = !hidden.has(name);
  return selected;
}

/** 숫자로 강제(파싱 불가 시 null). 히스토그램·박스·ecdf 의 수치 축 대응. */
function toNumber(v) {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

const MISSING_OPTION = { option: null, legendNames: [], row_ids: [], brushable: false };

/**
 * mark + points + 뷰 스냅샷으로 ECharts option 을 만든다(차트 종류별 분기).
 *
 * @param {string} mark  scatter|line|bar|box|histogram|ecdf|heatmap
 * @param {Array<{x:any,y:any,legend:any}>} points  해당 선택키의 전체 타점
 * @param {object} snapshot  {excluded, legend:{order,colors,hidden}}
 * @param {{xName?:string, yName?:string, roles?:{x:boolean,y:boolean,legend:boolean}, aggregate?:string}} opts
 * @returns {{option:object|null, legendNames:string[], row_ids:Array, brushable:boolean, error?:string}}
 */
export function buildChartOption(mark, points, snapshot, opts = {}) {
  const meta = MARK_BY_ID[mark] ?? MARK_BY_ID.scatter;
  const roles = opts.roles ?? { x: true, y: true, legend: true };
  const missing = meta.needs.filter((r) => !roles[r]);
  if (missing.length > 0) {
    return {
      ...MISSING_OPTION,
      error: `${meta.label} 차트는 ${missing
        .map((r) => ROLE_LABELS[r] ?? r)
        .join(" · ")} 컬럼 매핑이 필요합니다.`,
    };
  }

  const snap = snapshot ?? emptySnapshot();
  const excluded = new Set(snap.excluded ?? []);
  const ctx = {
    excluded,
    colors: snap.legend?.colors ?? {},
    hidden: new Set(snap.legend?.hidden ?? []),
    order: snap.legend?.order ?? null,
    xName: opts.xName || "x",
    yName: opts.yName || "y",
    aggregate: opts.aggregate || "mean",
  };

  switch (meta.id) {
    case "line":
      return buildLineLike(points, ctx, { ecdf: false });
    case "ecdf":
      return buildLineLike(points, ctx, { ecdf: true });
    case "bar":
      return buildBar(points, ctx);
    case "box":
      return buildBox(points, ctx);
    case "histogram":
      return buildHistogram(points, ctx);
    case "heatmap":
      return buildHeatmap(points, ctx);
    case "scatter":
    default:
      return buildScatter(points, ctx);
  }
}

/** scatter — 점이 원본 행과 1:1. brush 네이티브 지원. */
function buildScatter(points, ctx) {
  const groups = groupByLegend(points, ctx.excluded);
  const legendNames = resolveLegendOrder([...groups.keys()], ctx.order);
  const row_ids = [];
  const xValues = [];
  const series = legendNames.map((name, idx) => {
    const rows = groups.get(name) ?? [];
    row_ids.push(rows.map((r) => r.idx));
    for (const r of rows) xValues.push(r.x);
    return {
      name,
      type: "scatter",
      data: rows.map((r) => [r.x, r.y]),
      symbolSize: 10,
      itemStyle: { color: colorFor(name, idx, ctx.colors) },
      emphasis: { focus: "series" },
    };
  });

  const option = {
    tooltip: { trigger: "item" },
    legend: { data: legendNames, selected: selectedMap(legendNames, ctx.hidden), top: 8, right: 12, type: "scroll" },
    grid: { left: 56, right: 28, top: 40, bottom: 60 },
    xAxis: { type: detectAxisType(xValues), name: ctx.xName, nameLocation: "middle", nameGap: 28 },
    yAxis: { type: "value", name: ctx.yName, scale: true },
    series,
  };
  return { option, legendNames, row_ids, brushable: true };
}

/**
 * line / ecdf 공용 — 둘 다 선이라 ECharts brush 가 점을 못 잡으므로 투명 scatter
 * 트윈(overlay)을 덧씌워 brush 선택을 가능케 한다(메인 앱 _with_brush_overlay 패턴).
 * ecdf 는 그룹별로 x 를 정렬해 누적비율 i/n 계단선을 그린다.
 */
function buildLineLike(points, ctx, { ecdf }) {
  const groups = groupByLegend(points, ctx.excluded);
  const legendNames = resolveLegendOrder([...groups.keys()], ctx.order);
  const series = [];
  const row_ids = [];
  const xValues = [];

  legendNames.forEach((name, idx) => {
    const color = colorFor(name, idx, ctx.colors);
    let lineData;
    let overlayData;
    let ids;
    if (ecdf) {
      const sorted = (groups.get(name) ?? [])
        .map((r) => ({ x: toNumber(r.x), idx: r.idx }))
        .filter((r) => r.x !== null)
        .sort((a, b) => a.x - b.x);
      const n = sorted.length;
      lineData = sorted.map((r, i) => [r.x, (i + 1) / n]);
      overlayData = lineData;
      ids = sorted.map((r) => r.idx);
      for (const r of sorted) xValues.push(r.x);
    } else {
      const rows = (groups.get(name) ?? [])
        .slice()
        .sort((a, b) => sortKey(a.x) - sortKey(b.x));
      lineData = rows.map((r) => [r.x, r.y]);
      overlayData = lineData;
      ids = rows.map((r) => r.idx);
      for (const r of rows) xValues.push(r.x);
    }

    series.push({
      name,
      type: "line",
      step: ecdf ? "end" : false,
      showSymbol: !ecdf,
      symbolSize: 7,
      data: lineData,
      itemStyle: { color },
      lineStyle: { color },
    });
    row_ids.push(null); // 본체 line 은 brush 대상 아님(overlay 가 담당).

    // 투명 scatter 트윈 — brush hit-test 만 담당.
    series.push({
      name,
      type: "scatter",
      data: overlayData,
      symbolSize: 12,
      itemStyle: { color, opacity: 0 },
      emphasis: { disabled: true },
      tooltip: { show: false },
      silent: true,
      z: 5,
    });
    row_ids.push(ids);
  });

  const option = {
    tooltip: { trigger: "axis" },
    legend: { data: legendNames, selected: selectedMap(legendNames, ctx.hidden), top: 8, right: 12, type: "scroll" },
    grid: { left: 56, right: 28, top: 40, bottom: 60 },
    xAxis: {
      type: ecdf ? "value" : detectAxisType(xValues),
      name: ctx.xName,
      nameLocation: "middle",
      nameGap: 28,
    },
    yAxis: ecdf
      ? { type: "value", name: "누적 비율", min: 0, max: 1 }
      : { type: "value", name: ctx.yName, scale: true },
    series,
  };
  return { option, legendNames, row_ids, brushable: true };
}

/** line 정렬 키 — 숫자/시간은 수치, 범주는 0(원순서 유지). */
function sortKey(v) {
  if (typeof v === "number") return v;
  const t = Date.parse(v);
  return Number.isNaN(t) ? 0 : t;
}

/** bar — x 범주별 y 집계(같은 x 묶음). 점↔행 역추적 불가라 brush 미지원. */
function buildBar(points, ctx) {
  const groups = groupByLegend(points, ctx.excluded);
  const legendNames = resolveLegendOrder([...groups.keys()], ctx.order);

  // x 카테고리: 모든 그룹에서 등장한 x 값을 등장 순서로 수집.
  const categories = [];
  const seen = new Set();
  for (const rows of groups.values()) {
    for (const r of rows) {
      const key = String(r.x);
      if (!seen.has(key)) {
        seen.add(key);
        categories.push(key);
      }
    }
  }

  const series = legendNames.map((name, idx) => {
    const rows = groups.get(name) ?? [];
    const byCat = new Map(); // catKey -> [y...]
    for (const r of rows) {
      const key = String(r.x);
      if (!byCat.has(key)) byCat.set(key, []);
      const y = toNumber(r.y);
      if (y !== null) byCat.get(key).push(y);
    }
    const data = categories.map((cat) => aggregate(byCat.get(cat) ?? [], ctx.aggregate));
    return {
      name,
      type: "bar",
      data,
      itemStyle: { color: colorFor(name, idx, ctx.colors) },
    };
  });

  const option = {
    tooltip: { trigger: "axis" },
    legend: { data: legendNames, selected: selectedMap(legendNames, ctx.hidden), top: 8, right: 12, type: "scroll" },
    grid: { left: 56, right: 28, top: 40, bottom: 60 },
    xAxis: { type: "category", name: ctx.xName, data: categories },
    yAxis: { type: "value", name: ctx.yName, scale: true },
    series,
  };
  return { option, legendNames, row_ids: series.map(() => null), brushable: false };
}

/** 집계 함수 적용(빈 리스트면 null → 막대 공백). */
function aggregate(values, fn) {
  if (fn === "count") return values.length;
  if (values.length === 0) return null;
  if (fn === "sum") return values.reduce((a, b) => a + b, 0);
  if (fn === "min") return Math.min(...values);
  if (fn === "max") return Math.max(...values);
  // mean (기본)
  return values.reduce((a, b) => a + b, 0) / values.length;
}

/** box — legend 그룹별 [min,Q1,median,Q3,max] 박스. 단일 boxplot 시리즈(그룹=카테고리). */
function buildBox(points, ctx) {
  const groups = groupByLegend(points, ctx.excluded);
  const allNames = resolveLegendOrder([...groups.keys()], ctx.order);
  // Hide 된 그룹은 카테고리에서 제거(box 는 단일 시리즈라 legend.selected 로 못 가림).
  const visible = allNames.filter((name) => !ctx.hidden.has(name));

  const data = visible.map((name, idx) => {
    const ys = (groups.get(name) ?? [])
      .map((r) => toNumber(r.y))
      .filter((v) => v !== null)
      .sort((a, b) => a - b);
    return {
      value: boxStats(ys),
      itemStyle: {
        color: colorFor(name, allNames.indexOf(name), ctx.colors),
        borderColor: colorFor(name, allNames.indexOf(name), ctx.colors),
      },
    };
  });

  const option = {
    tooltip: { trigger: "item" },
    grid: { left: 56, right: 28, top: 24, bottom: 60 },
    xAxis: { type: "category", name: ctx.xName || "그룹", data: visible },
    yAxis: { type: "value", name: ctx.yName, scale: true },
    series: [{ name: ctx.yName, type: "boxplot", data }],
  };
  // legendNames 는 편집 패널이 그룹 색/순서/Filter 를 다루도록 전체 그룹명을 노출.
  return { option, legendNames: allNames, row_ids: [null], brushable: false };
}

/** [min, Q1, median, Q3, max] (선형보간 분위수 — polars quantile linear 와 동치). */
function boxStats(sorted) {
  if (sorted.length === 0) return [0, 0, 0, 0, 0];
  return [
    sorted[0],
    quantileLinear(sorted, 0.25),
    quantileLinear(sorted, 0.5),
    quantileLinear(sorted, 0.75),
    sorted[sorted.length - 1],
  ];
}

function quantileLinear(sorted, q) {
  const n = sorted.length;
  if (n === 1) return sorted[0];
  const pos = q * (n - 1);
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  if (lo === hi) return sorted[lo];
  return sorted[lo] * (hi - pos) + sorted[hi] * (pos - lo);
}

/** histogram — x 를 전체 범위 공유 10빈으로 나눠 그룹별 카운트(겹친 막대). */
function buildHistogram(points, ctx) {
  const groups = groupByLegend(points, ctx.excluded);
  const legendNames = resolveLegendOrder([...groups.keys()], ctx.order);

  const allX = [];
  for (const rows of groups.values()) {
    for (const r of rows) {
      const x = toNumber(r.x);
      if (x !== null) allX.push(x);
    }
  }
  if (allX.length === 0) {
    return { ...MISSING_OPTION, error: "히스토그램: 수치 데이터가 없습니다." };
  }
  const bins = equalWidthBins(allX, HISTOGRAM_BIN_COUNT);
  const labels = [];
  for (let i = 0; i < bins.length - 1; i++) {
    labels.push(`[${bins[i].toFixed(2)}, ${bins[i + 1].toFixed(2)})`);
  }

  const series = legendNames.map((name, idx) => {
    const xs = (groups.get(name) ?? [])
      .map((r) => toNumber(r.x))
      .filter((v) => v !== null);
    return {
      name,
      type: "bar",
      data: binCounts(xs, bins),
      itemStyle: { color: colorFor(name, idx, ctx.colors) },
      barGap: 0,
    };
  });

  const option = {
    tooltip: { trigger: "axis" },
    legend: { data: legendNames, selected: selectedMap(legendNames, ctx.hidden), top: 8, right: 12, type: "scroll" },
    grid: { left: 56, right: 28, top: 40, bottom: 70 },
    xAxis: { type: "category", name: ctx.xName, data: labels, axisLabel: { rotate: 30, fontSize: 9 } },
    yAxis: { type: "value", name: "빈도" },
    series,
  };
  return { option, legendNames, row_ids: series.map(() => null), brushable: false };
}

function equalWidthBins(values, count) {
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  if (lo === hi) hi = lo + 1;
  const step = (hi - lo) / count;
  const bins = [];
  for (let i = 0; i <= count; i++) bins.push(lo + step * i);
  return bins;
}

function binCounts(values, bins) {
  const counts = new Array(bins.length - 1).fill(0);
  for (const v of values) {
    for (let i = 0; i < bins.length - 1; i++) {
      const lastBin = i === bins.length - 2;
      if ((v >= bins[i] && v < bins[i + 1]) || (lastBin && v === bins[i + 1])) {
        counts[i] += 1;
        break;
      }
    }
  }
  return counts;
}

/** heatmap — x(범주) × y(범주) 셀별 카운트 밀도(색=카운트). legend 미사용. */
function buildHeatmap(points, ctx) {
  const live = [];
  points.forEach((p, i) => {
    if (!ctx.excluded.has(i)) live.push(p);
  });
  const xCats = [];
  const yCats = [];
  const xIdx = new Map();
  const yIdx = new Map();
  for (const p of live) {
    const xk = String(p.x);
    const yk = String(p.y);
    if (!xIdx.has(xk)) { xIdx.set(xk, xCats.length); xCats.push(xk); }
    if (!yIdx.has(yk)) { yIdx.set(yk, yCats.length); yCats.push(yk); }
  }
  const cellCount = new Map(); // "xi,yi" -> count
  for (const p of live) {
    const key = `${xIdx.get(String(p.x))},${yIdx.get(String(p.y))}`;
    cellCount.set(key, (cellCount.get(key) ?? 0) + 1);
  }
  const data = [];
  let maxCount = 0;
  for (const [key, count] of cellCount) {
    const [xi, yi] = key.split(",").map(Number);
    data.push([xi, yi, count]);
    if (count > maxCount) maxCount = count;
  }

  const option = {
    tooltip: { trigger: "item" },
    grid: { left: 70, right: 28, top: 24, bottom: 80 },
    xAxis: { type: "category", name: ctx.xName, data: xCats, axisLabel: { rotate: 30, fontSize: 9 } },
    yAxis: { type: "category", name: ctx.yName, data: yCats },
    visualMap: {
      min: 0,
      max: Math.max(1, maxCount),
      calculable: true,
      orient: "horizontal",
      left: "center",
      bottom: 8,
    },
    series: [{ name: "빈도", type: "heatmap", data }],
  };
  // heatmap 은 legend 그룹을 쓰지 않으므로 편집 패널을 비활성(빈 목록).
  return { option, legendNames: [], row_ids: [null], brushable: false };
}
