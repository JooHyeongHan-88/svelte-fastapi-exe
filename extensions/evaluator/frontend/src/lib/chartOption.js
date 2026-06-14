// 선택 항목(선택키)별 scatter ECharts option 을 클라이언트에서 구성한다.
//
// 메인 앱의 display_chart 는 백엔드 render_spec_to_echarts + /api/chart/filter 파이프라인을
// 거치지만, evaluator 의 차트는 이미 클라이언트에 적재된 points 를 보고 큐레이션을 판단하는
// 휘발성 검토 도구다. 따라서 격리 원칙에 따라 메인 앱 파이프라인에 결합하지 않고 option 을
// 클라이언트에서 직접 만든다(필터·레전드도 클라이언트 상태). buildScatterOption 은 제외(brush
// Filter)·레전드(순서·색상·Hide) 스냅샷을 반영하고, brush 선택을 원본 point 인덱스로 되돌릴
// row_ids 를 함께 돌려준다.

// ECharts 기본 팔레트 — 색상 오버라이드 전 스와치/시리즈 색의 기준(메인 앱과 동일).
export const ECHARTS_PALETTE = [
  "#5470c6", "#91cc75", "#fac858", "#ee6666", "#73c0de",
  "#3ba272", "#fc8452", "#9a60b4", "#ea7ccc",
];

const LEGEND_FALLBACK = "—";

/** 빈(초기) 뷰 스냅샷 — 제외 없음 · 레전드 오버라이드 없음. */
export function emptySnapshot() {
  return { excluded: [], legend: { order: null, colors: {}, hidden: [] } };
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
 * 한 선택키의 points + 뷰 스냅샷으로 scatter ECharts option 을 만든다.
 *
 * @param {Array<{x:any, y:any, legend:any}>} points  해당 선택키의 전체 타점
 * @param {{excluded:number[], legend:{order:string[]|null, colors:Record<string,string>, hidden:string[]}}} snapshot
 * @param {{xName?:string, yName?:string, dark?:boolean}} opts  (제목은 감싼 패널이 표시 — 차트에 두지 않음)
 * @returns {{option:object, legendNames:string[], row_ids:number[][]}}
 *   option: ECharts setOption 대상.
 *   legendNames: 표시 순서대로의 레전드 이름.
 *   row_ids: 시리즈별 원본 point 인덱스 배열(brush 선택 → 제외 인덱스 환원용).
 */
export function buildScatterOption(points, snapshot, opts = {}) {
  const { xName = "x", yName = "y", dark = false } = opts;
  const snap = snapshot ?? emptySnapshot();
  const excluded = new Set(snap.excluded ?? []);
  const colors = snap.legend?.colors ?? {};
  const hidden = new Set(snap.legend?.hidden ?? []);

  // 레전드별로 (제외되지 않은) 타점과 원본 인덱스를 모은다.
  const groups = new Map(); // name -> { data: [[x,y]], rowIds: [origIndex] }
  const xValues = [];
  points.forEach((p, i) => {
    if (excluded.has(i)) return;
    const name = p.legend ?? LEGEND_FALLBACK;
    if (!groups.has(name)) groups.set(name, { data: [], rowIds: [] });
    const g = groups.get(name);
    g.data.push([p.x, p.y]);
    g.rowIds.push(i);
    xValues.push(p.x);
  });

  const legendNames = resolveLegendOrder([...groups.keys()], snap.legend?.order);
  const row_ids = [];
  const series = legendNames.map((name, idx) => {
    const g = groups.get(name) ?? { data: [], rowIds: [] };
    row_ids.push(g.rowIds);
    const color = colors[name] ?? ECHARTS_PALETTE[idx % ECHARTS_PALETTE.length];
    return {
      name,
      type: "scatter",
      data: g.data,
      symbolSize: 10,
      itemStyle: { color },
      emphasis: { focus: "series" },
    };
  });

  const selected = {};
  for (const name of legendNames) selected[name] = !hidden.has(name);

  // 차트 자체 제목은 두지 않는다 — 감싼 패널(그리드 셀 헤더·라이트박스 헤더)이 이미
  // 제목을 표시하므로 캔버스 안 제목은 중복이다.
  const option = {
    backgroundColor: dark ? "transparent" : undefined,
    tooltip: { trigger: "item" },
    legend: { data: legendNames, selected, top: 8, right: 12, type: "scroll" },
    grid: { left: 56, right: 28, top: 40, bottom: 60 },
    xAxis: {
      type: detectAxisType(xValues),
      name: xName,
      nameLocation: "middle",
      nameGap: 28,
    },
    yAxis: { type: "value", name: yName, scale: true },
    series,
  };

  return { option, legendNames, row_ids };
}
