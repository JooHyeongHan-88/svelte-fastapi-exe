// 아티팩트 패널 액션 — display_image / display_chart / display_markdown 결과 관리.
//
// 영속화 모델: payload 는 ui.* 휘발 상태가 아니라 메시지의 artifactChips 안에 통째로
// 임베드된다. localStorage 가 메시지를 직렬화할 때 자연스럽게 함께 보존되므로,
// 세션을 나갔다 다시 들어와도 칩을 클릭하면 동일 산출물이 패널에 다시 표시된다.

import { ui, activeSession } from "./state.svelte.js";
import { saveArtifactPanelOpen } from "./storage.js";
import { postChartFilter, getChartFilterState } from "./api.js";

/**
 * 새 아티팩트 칩 객체를 만든다 (메시지에 직접 임베드할 형태).
 *
 * @param {"image"|"chart"|"markdown"} kind
 * @param {object} payload  - ToolResultEvent.data (kind 필드 포함)
 * @returns {{
 *   id: string,
 *   kind: "image"|"chart"|"markdown",
 *   label: string,
 *   payload: object,
 *   createdAt: number,
 * }}
 */
export function makeArtifactChip(kind, payload) {
  const id = `artifact-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  return {
    id,
    kind,
    label: _artifactLabel(kind, payload),
    payload,
    createdAt: Date.now(),
  };
}

/**
 * 칩을 활성화 — 활성 세션 메시지에서 해당 id 의 칩을 찾아 패널 상태를 갱신한다.
 * 매번 활성 세션의 메시지를 평탄화 탐색하므로 휘발 메모리에 의존하지 않는다.
 *
 * @param {string} id
 */
export function openArtifact(id) {
  const chip = _findChip(id);
  if (!chip) return;
  ui.activeArtifactId = id;
  ui.artifactPanelOpen = true;
  saveArtifactPanelOpen(true);
}

/** 패널 닫기 (칩은 메시지에 그대로 — 다시 클릭하면 열림). */
export function closeArtifactPanel() {
  ui.artifactPanelOpen = false;
  saveArtifactPanelOpen(false);
}

/** 패널 토글. */
export function toggleArtifactPanel() {
  ui.artifactPanelOpen = !ui.artifactPanelOpen;
  saveArtifactPanelOpen(ui.artifactPanelOpen);
}

/**
 * 세션 전환 시 활성 칩 id 만 리셋한다 — 새 세션의 칩 목록과 무관하므로 비워둔다.
 * 패널 가시성(artifactPanelOpen) 은 사용자가 명시적으로 토글하지 않는 한 유지한다 (sticky UX).
 * payload 는 메시지에 영속되므로 비울 게 없다.
 */
export function resetArtifactPanelState() {
  ui.activeArtifactId = null;
}

/**
 * 활성 세션의 모든 메시지에서 artifactChips 를 createdAt 순으로 평탄화한다.
 * ArtifactPanel 의 탭 바와 활성 칩 조회에 모두 사용.
 *
 * @returns {Array<{id, kind, label, payload, createdAt}>}
 */
export function listSessionArtifacts() {
  const session = activeSession();
  if (!session) return [];
  const out = [];
  for (const m of session.messages) {
    if (m.artifactChips && m.artifactChips.length > 0) {
      for (const chip of m.artifactChips) {
        out.push(chip);
      }
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// 내부 헬퍼
// ---------------------------------------------------------------------------

function _findChip(id) {
  const session = activeSession();
  if (!session) return null;
  for (const m of session.messages) {
    if (!m.artifactChips) continue;
    for (const chip of m.artifactChips) {
      if (chip.id === id) return chip;
    }
  }
  return null;
}

function _artifactLabel(kind, payload) {
  if (kind === "image") {
    const items = Array.isArray(payload?.items) ? payload.items : [];
    if (items.length > 1) return `이미지 ${items.length}장`;
    const single = items[0] ?? {};
    return single.alt || single.caption || "이미지";
  }
  if (kind === "chart") {
    const items = Array.isArray(payload?.items) ? payload.items : [];
    if (items.length > 1) return `차트 ${items.length}개`;
    const single = items[0] ?? {};
    const typeLabel = {
      scatter: "산점도",
      line: "꺾은선",
      bar: "막대",
      histogram: "히스토그램",
      box: "박스플롯",
      heatmap: "히트맵",
    };
    const t = typeLabel[single.chart_type] || "차트";
    return single.title || t;
  }
  if (kind === "markdown") {
    return payload.title || "마크다운 문서";
  }
  return "아티팩트";
}

// ---------------------------------------------------------------------------
// Lightbox — 이미지·차트 셀 클릭 시 확대 모달
// ---------------------------------------------------------------------------

/**
 * 라이트박스를 연다. items 는 같은 payload 안의 형제 항목들이며 좌/우 화살표로
 * 순회할 수 있다.
 *
 * @param {"image"|"chart"} kind
 * @param {any[]} items
 * @param {number} index
 */
export function openLightbox(kind, items, index = 0) {
  if (!Array.isArray(items) || items.length === 0) return;
  const safeIndex = Math.min(Math.max(0, index), items.length - 1);
  // 프로퍼티 개별 변경으로 ui.lightbox 객체 레퍼런스를 유지한다.
  // 객체 교체(spread) 시 open 외 다른 프로퍼티 변경도 $effect(() => open) 을 재실행시켜
  // 모달 크기가 초기화되는 부작용이 발생한다.
  ui.lightbox.kind = kind;
  ui.lightbox.items = items;
  ui.lightbox.index = safeIndex;
  ui.lightbox.open = true;
}

export function closeLightbox() {
  ui.lightbox.open = false;
}

export function lightboxPrev() {
  if (!ui.lightbox.open) return;
  const total = _lightboxTotal();
  if (total <= 1) return;
  ui.lightbox.index = (ui.lightbox.index - 1 + total) % total;
}

export function lightboxNext() {
  if (!ui.lightbox.open) return;
  const total = _lightboxTotal();
  if (total <= 1) return;
  ui.lightbox.index = (ui.lightbox.index + 1) % total;
}

function _lightboxTotal() {
  if (ui.lightbox.kind === "chart" && ui.lightbox.chartKey) {
    return ui.chartCache[ui.lightbox.chartKey]?.items?.length ?? 0;
  }
  return ui.lightbox.items.length;
}

// ---------------------------------------------------------------------------
// 차트 인터랙티브 필터
// ---------------------------------------------------------------------------

/**
 * ArtifactChart 가 마운트되거나 payload 가 바뀔 때 호출해 chartCache 를 채운다.
 * 이미 캐시에 있으면 no-op.
 *
 * @param {{ src: string, spec?: string }} payload
 */
export async function loadChartCache(payload) {
  const key = payload?.src;
  if (!key) return;
  if (ui.chartCache[key]) return;

  ui.chartCache[key] = { items: [], status: "loading", error: "", canUndo: false, canRedo: false };

  try {
    const r = await fetch(key, { cache: "no-cache" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    const items = Array.isArray(data) ? data : [];

    // 필터 상태 초기값 (spec 이 있을 때만 조회)
    let canUndo = false;
    let canRedo = false;
    if (payload.spec) {
      const fs = await getChartFilterState(payload.spec);
      canUndo = fs.can_undo ?? false;
      canRedo = fs.can_redo ?? false;
    }

    ui.chartCache[key] = { items, status: "ok", error: "", canUndo, canRedo };
  } catch (err) {
    ui.chartCache[key] = {
      items: [],
      status: "error",
      error: String(err?.message ?? err),
      canUndo: false,
      canRedo: false,
    };
  }
}

/**
 * 차트 라이트박스를 연다. chartKey 와 specPath 를 기록해 필터 동기화에 사용한다.
 *
 * @param {{ src: string, spec?: string }} payload
 * @param {number} index
 */
export function openChartLightbox(payload, index = 0) {
  const key = payload?.src;
  if (!key) return;
  const items = ui.chartCache[key]?.items ?? [];
  const safeIndex = Math.min(Math.max(0, index), Math.max(0, items.length - 1));

  ui.lightbox.kind = "chart";
  ui.lightbox.chartKey = key;
  ui.lightbox.specPath = payload.spec ?? null;
  ui.lightbox.index = safeIndex;
  // items 는 이미지 전용 — 차트는 chartCache 경유이므로 비운다.
  ui.lightbox.items = [];
  ui.lightbox.open = true;
}

/**
 * 공통 필터 액션 실행 헬퍼.
 *
 * @param {object} body  postChartFilter 에 전달할 요청 본문
 */
async function _applyChartFilter(body) {
  const key = ui.lightbox.chartKey;
  const spec = ui.lightbox.specPath;
  if (!key || !spec) return;

  const entry = ui.chartCache[key];
  if (!entry) return;

  try {
    const result = await postChartFilter({ spec, ...body });
    // 응답으로 캐시 갱신 → ArtifactChart(그리드) + Lightbox(모달) 동시 재렌더
    ui.chartCache[key] = {
      items: result.items ?? [],
      status: "ok",
      error: "",
      canUndo: result.can_undo ?? false,
      canRedo: result.can_redo ?? false,
    };
  } catch (err) {
    console.error("chart filter failed:", err);
  }
}

/**
 * 현재 라이트박스에서 brush 로 선택한 타점을 제외 필터링한다.
 *
 * @param {"single"|"all"} scope
 * @param {number} chartIndex  brush 가 일어난 차트의 인덱스
 * @param {number[]} rowIds  제외할 원본 parquet 행 인덱스
 */
export async function filterChartSelection(scope, chartIndex, rowIds) {
  await _applyChartFilter({
    action: "exclude",
    scope,
    chart_index: chartIndex,
    row_ids: rowIds,
  });
}

/** 1단계 이전 필터 상태로 되돌린다. */
export async function undoChartFilter() {
  await _applyChartFilter({ action: "undo" });
}

/** 되돌린 상태에서 1단계 앞으로 다시 실행한다. */
export async function redoChartFilter() {
  await _applyChartFilter({ action: "redo" });
}

/** 모든 필터를 초기화한다 (undo 로 복구 가능). */
export async function resetChartFilter() {
  await _applyChartFilter({ action: "reset" });
}
