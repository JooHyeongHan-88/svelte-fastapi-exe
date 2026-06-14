// 선택키별 차트 뷰 상태 스토어 — 제외(brush Filter)와 레전드(순서·색상·Hide)를 단일
// undo/redo 스냅샷 스택으로 통합한다(메인 앱 chart_filter_store v2 의 클라이언트 버전).
//
// evaluator 차트는 휘발성 검토 도구라 백엔드에 영속하지 않는다. 그리드 셀과 라이트박스가
// 같은 스토어를 참조하므로 어느 쪽에서 필터해도 양쪽이 동시 재렌더된다(메인 앱 chartCache
// 와 동일한 단일 진실원천 패턴).

import { emptySnapshot } from "./chartOption.js";

// byKey: 선택키 -> { stack: Snapshot[], cursor: number }. cursor 가 가리키는 스냅샷이 현재.
export const chartStore = $state({ byKey: {} });

function _ensure(key) {
  if (!chartStore.byKey[key]) {
    chartStore.byKey[key] = { stack: [emptySnapshot()], cursor: 0 };
  }
  return chartStore.byKey[key];
}

/** 현재 스냅샷(읽기 전용으로 취급). 없으면 빈 스냅샷. */
export function currentSnapshot(key) {
  const entry = chartStore.byKey[key];
  if (!entry) return emptySnapshot();
  return entry.stack[entry.cursor];
}

export function canUndo(key) {
  const entry = chartStore.byKey[key];
  return !!entry && entry.cursor > 0;
}

export function canRedo(key) {
  const entry = chartStore.byKey[key];
  return !!entry && entry.cursor < entry.stack.length - 1;
}

/** 필터/레전드가 한 번이라도 적용됐는지 (Reset 활성 조건). */
export function hasView(key) {
  return canUndo(key);
}

// 새 스냅샷을 push — redo 꼬리를 자르고 cursor 를 끝으로 옮긴다. 배열을 새로 할당해
// Svelte 반응성을 보장한다.
function _push(key, snapshot) {
  const entry = _ensure(key);
  const trimmed = entry.stack.slice(0, entry.cursor + 1);
  entry.stack = [...trimmed, snapshot];
  entry.cursor = entry.stack.length - 1;
}

function _dedupe(list) {
  return [...new Set(list)];
}

/**
 * brush/레전드로 선택한 원본 point 인덱스를 현재 키의 차트에서 제외한다(레전드 carry).
 *
 * @param {string} key
 * @param {number[]} indices  제외할 point 인덱스
 */
export function applyExclude(key, indices) {
  if (!Array.isArray(indices) || indices.length === 0) return;
  const cur = currentSnapshot(key);
  _push(key, {
    excluded: _dedupe([...(cur.excluded ?? []), ...indices]),
    legend: cur.legend,
  });
}

/**
 * 레전드 오버라이드를 갱신한다(제외 carry). order/hidden 은 통째 교체, colors 는 병합.
 *
 * @param {string} key
 * @param {{order?:string[], colors?:Record<string,string>, hidden?:string[]}} patch
 */
export function applyLegend(key, patch) {
  const cur = currentSnapshot(key);
  const legend = cur.legend ?? { order: null, colors: {}, hidden: [] };
  _push(key, {
    excluded: cur.excluded ?? [],
    legend: {
      order: patch.order !== undefined ? patch.order : legend.order,
      colors: patch.colors ? { ...legend.colors, ...patch.colors } : legend.colors,
      hidden: patch.hidden !== undefined ? patch.hidden : legend.hidden,
    },
  });
}

/** 빈 스냅샷을 push 해 초기화한다(undo 로 복구 가능 — 메인 앱과 동일). */
export function reset(key) {
  if (!chartStore.byKey[key]) return;
  _push(key, emptySnapshot());
}

export function undo(key) {
  const entry = chartStore.byKey[key];
  if (entry && entry.cursor > 0) entry.cursor -= 1;
}

export function redo(key) {
  const entry = chartStore.byKey[key];
  if (entry && entry.cursor < entry.stack.length - 1) entry.cursor += 1;
}

/** 더 이상 표시하지 않는 키의 상태를 비운다(메모리 정리, 선택적). */
export function dropKeys(keepKeys) {
  const keep = new Set(keepKeys);
  for (const k of Object.keys(chartStore.byKey)) {
    if (!keep.has(k)) delete chartStore.byKey[k];
  }
}
