// 아티팩트 패널 액션 — display_image / display_chart / display_markdown 결과 관리.
//
// 영속화 모델: payload 는 ui.* 휘발 상태가 아니라 메시지의 artifactChips 안에 통째로
// 임베드된다. localStorage 가 메시지를 직렬화할 때 자연스럽게 함께 보존되므로,
// 세션을 나갔다 다시 들어와도 칩을 클릭하면 동일 산출물이 패널에 다시 표시된다.

import { ui, activeSession } from "./state.svelte.js";
import { saveArtifactPanelOpen } from "./storage.js";
import {
  postChartFilter,
  getChartFilterState,
  revealArtifactPath,
  listExtensions,
} from "./api.js";

/**
 * 새 아티팩트 칩 객체를 만든다 (메시지에 직접 임베드할 형태).
 *
 * @param {"image"|"chart"|"markdown"|"data"} kind
 * @param {object} payload  - ToolResultEvent.data (data 칩은 {path, filename, ...})
 * @returns {{
 *   id: string,
 *   kind: "image"|"chart"|"markdown"|"data",
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

/**
 * 칩이 가리키는 산출물의 'result/...' 참조 경로를 돌려준다 (없으면 null).
 *
 * 백엔드 load_artifact / display_* 도구가 그대로 해석할 수 있는 형태로 환원한다.
 * data URI·외부 URL·workspace/assets 경로는 load_artifact 대상이 아니므로 제외하고,
 * 인용 가능한 경로가 하나도 없으면 null (호출부가 '참조' 버튼을 숨긴다).
 * 다중 이미지 갤러리는 인용 가능한 모든 항목을 줄바꿈으로 이어 반환한다 —
 * 첫 항목만 반환하면 나머지가 조용히 누락돼 "이 산출물로 작업해줘" 의도를 깬다.
 * 구분자가 줄바꿈인 이유: 세션 폴더명이 사용자 메시지 제목 기반이라 경로 자체에
 * 공백이 들어갈 수 있어 공백 구분은 경로 경계가 모호해진다.
 *
 * @param {{kind:string, payload:object}} chip
 * @returns {string|null}
 */
export function artifactRefPath(chip) {
  if (!chip) return null;
  if (chip.kind === "chart") {
    // display_chart 가 ToolResult.data.spec 에 'result/...charts.spec.json' 을 영속.
    // parquet 은 spec 의 data.source 로 연계 발견되므로 spec 하나가 인용 단위.
    const spec = chip.payload?.spec;
    return typeof spec === "string" && spec.startsWith("result/") ? spec : null;
  }
  if (chip.kind === "markdown") {
    return _resultUrlToRel(chip.payload?.src);
  }
  if (chip.kind === "image") {
    const items = Array.isArray(chip.payload?.items) ? chip.payload.items : [];
    const paths = items.map((it) => _resultUrlToRel(it?.src)).filter(Boolean);
    return paths.length > 0 ? paths.join("\n") : null;
  }
  if (chip.kind === "data") {
    // save_artifact / exec_code 가 반환한 'result/...' 경로가 payload 에 그대로 영속.
    const path = chip.payload?.path;
    return typeof path === "string" && path.startsWith("result/") ? path : null;
  }
  return null;
}

/**
 * 칩의 참조 경로를 Composer 입력창 커서 위치에 인라인 pill 로 삽입하라고 신호한다
 * ("이 산출물로 작업해줘" UX). 패널 열기(openArtifact)와 독립적으로 동작하므로
 * 호출부가 stopPropagation 해야 한다. 이미지 갤러리처럼 경로가 여러 개면(줄바꿈 구분)
 * 각 경로를 개별 pill 로 삽입한다.
 *
 * 실제 DOM 삽입은 Composer 가 contenteditable 에서 수행한다 — 액션 레이어는 신호만 둔다.
 *
 * @param {string} chipId
 */
export function insertArtifactReference(chipId) {
  const chip = _findChip(chipId);
  if (!chip) return;
  const ref = artifactRefPath(chip);
  if (!ref) return;
  const items = ref
    .split("\n")
    .filter(Boolean)
    .map((path) => ({ path, label: _refLabel(path) }));
  if (items.length === 0) return;
  ui.composerInsertRef = { items, nonce: Date.now() + Math.random() };
}

/** 경로 끝 세그먼트(파일명/폴더명)만 추출 — 인용 pill 라벨용. */
function _refLabel(path) {
  const clean = String(path).replace(/\/+$/, "");
  const seg = clean.slice(clean.lastIndexOf("/") + 1);
  return seg || clean;
}

/** 큐레이션 요약을 사람이 읽는 한 줄 맥락 문구로 만든다(후속 프롬프트 머리말). */
function _curationFollowupText(summary) {
  const base = "이 큐레이션 결과로 이어서 작업해줘";
  if (!summary || typeof summary !== "object") return `${base}: `;
  const facts = [];
  if (Number.isFinite(summary.total) && Number.isFinite(summary.selected)) {
    facts.push(`후보 ${summary.total}개 중 ${summary.selected}개 선택`);
  }
  if (Number.isFinite(summary.excluded_rows) && summary.excluded_rows > 0) {
    facts.push(`${summary.excluded_rows}행 제외`);
  }
  const note = typeof summary.note === "string" ? summary.note.trim() : "";
  let text = base;
  if (facts.length > 0) text += ` (${facts.join(", ")})`;
  if (note) text += ` [메모: ${note}]`;
  return `${text}: `;
}

/**
 * 큐레이션 결과(데이터 칩)로 이어서 작업하도록 컴포저에 후속 프롬프트를 시드한다.
 * 결정 요약(보존 N/M·제외·메모)을 머리말 텍스트로, 큐레이션 parquet 경로를 인용 pill
 * 로 넣어, 사용자가 검토 후 전송하면 에이전트가 사람의 큐레이션 맥락을 안고 이어서
 * 작업한다. 기존 composerSetParts 신호를 그대로 재사용한다(Composer 가 소비).
 *
 * @param {{path?:string, filename?:string, summary?:object}} payload
 */
export function seedCurationFollowup(payload) {
  const path = payload?.path;
  if (typeof path !== "string" || !path.startsWith("result/")) return;
  ui.composerSetParts = {
    parts: [
      { type: "text", value: _curationFollowupText(payload?.summary) },
      { type: "ref", path, label: _refLabel(path) },
    ],
    nonce: Date.now() + Math.random(),
  };
}

/**
 * 활성 칩의 산출물이 저장된 폴더를 OS 파일 탐색기(Windows Explorer)에서 연다.
 * 이미지 갤러리는 과거 산출물 재표시가 섞일 수 있어 항목들이 서로 다른 턴 폴더에
 * 흩어질 수 있다 — 첫 경로만 열면 보고 있는 항목의 폴더가 아닐 수 있으므로
 * 고유 폴더마다 한 번씩 연다 (대부분 1개라 동작 변화 없음).
 *
 * @param {string} chipId
 * @returns {Promise<boolean>}  전부 성공하면 true — 호출부가 실패 피드백을 표시한다.
 */
export async function revealArtifactFolder(chipId) {
  const chip = _findChip(chipId);
  if (!chip) return false;
  const ref = artifactRefPath(chip);
  if (!ref) return false;

  // 폴더 단위로 중복 제거하되 요청에는 파일 경로를 그대로 보낸다 —
  // 부모 폴더 환원은 백엔드(artifact_reveal)의 단일 책임으로 남긴다.
  const seenFolders = new Set();
  const targets = [];
  for (const path of ref.split("\n")) {
    const folder = path.slice(0, path.lastIndexOf("/"));
    if (seenFolders.has(folder)) continue;
    seenFolders.add(folder);
    targets.push(path);
  }

  const results = await Promise.allSettled(
    targets.map((path) => revealArtifactPath(path)),
  );
  const failures = results.filter((r) => r.status === "rejected");
  for (const failure of failures) {
    console.error("reveal artifact folder failed:", failure.reason);
  }
  return failures.length === 0;
}

/** '/result/...' URL 형태를 백엔드가 받는 'result/...' 상대 경로로 환원한다. */
function _resultUrlToRel(src) {
  return typeof src === "string" && src.startsWith("/result/") ? src.slice(1) : null;
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
  // 휘발 확장 뷰는 세션 산출물이 아니므로 세션 전환 시 정리한다.
  ui.extensionView = null;
}

// ---------------------------------------------------------------------------
// 확장(extensions) 런처 — 패널 열기 버튼의 드롭다운으로 확장을 패널에 연다.
// open_curation 이 만든 확장 칩(메시지 영속)과 달리, 여기서 연 확장은 휘발 뷰다.
// ---------------------------------------------------------------------------

/** 부팅 시 1회 — 패널 런처가 띄울 수 있는 확장 카탈로그를 캐시한다. */
export async function loadExtensions() {
  ui.extensions = await listExtensions();
}

/** 런처 드롭다운 토글/닫기. */
export function toggleExtensionMenu() {
  ui.extensionMenuOpen = !ui.extensionMenuOpen;
}

export function closeExtensionMenu() {
  ui.extensionMenuOpen = false;
}

/**
 * 확장을 우측 패널에 휘발 뷰로 연다 (소스/번들 없이 → 확장의 랜딩 페이지).
 * 같은 출처 iframe(/ext/<tool>/)을 임베드하고, 활성 칩으로 만들어 패널을 띄운다.
 *
 * @param {string} tool  확장 툴 이름 (ui.extensions[].tool)
 */
export function openExtensionPanel(tool) {
  const meta = ui.extensions.find((e) => e.tool === tool);
  const title = meta?.name || tool;
  ui.extensionView = {
    id: `ext-${tool}-${Date.now()}`,
    kind: "extension",
    label: title,
    payload: { tool, src: `/ext/${tool}/`, title },
  };
  ui.activeArtifactId = ui.extensionView.id;
  ui.artifactPanelOpen = true;
  saveArtifactPanelOpen(true);
  ui.extensionMenuOpen = false;
}

/** 휘발 확장 뷰를 닫는다 (탭의 × — 메시지 칩은 영향 없음). */
export function closeExtensionView() {
  ui.extensionView = null;
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
  // 휘발 확장 뷰(드롭다운 런처)도 활성화 대상 — 메시지 칩과 동일하게 탭 클릭으로 연다.
  if (ui.extensionView && ui.extensionView.id === id) return ui.extensionView;
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
  if (kind === "extension") {
    return payload.title || payload.tool || "확장 도구";
  }
  if (kind === "data") {
    const name = payload?.filename || "데이터";
    // save_artifact 경유는 rows/columns 를 알지만 exec_code 직접 쓰기는 모른다 —
    // 그 경우 패널의 preview fetch 가 정확한 형태를 보여준다.
    if (Number.isFinite(payload?.rows) && Number.isFinite(payload?.columns)) {
      return `${name} · ${payload.rows.toLocaleString()}×${payload.columns}`;
    }
    return name;
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

// ---------------------------------------------------------------------------
// 레전드 컨트롤 (순서·색상·Hide·Filter)
// ---------------------------------------------------------------------------

/**
 * 선택한 레전드(시리즈) 그룹의 원본 행을 데이터에서 제외한다.
 * 백엔드가 color.field 값으로 행을 환원해 기존 exclude 메커니즘으로 처리하므로
 * Undo/Reset/Filter All 이 brush 필터와 동일하게 동작한다.
 *
 * @param {"single"|"all"} scope
 * @param {number} chartIndex  현재 차트 인덱스
 * @param {string[]} values  제외할 레전드 이름 배열
 */
export async function excludeLegend(scope, chartIndex, values) {
  if (!Array.isArray(values) || values.length === 0) return;
  await _applyChartFilter({
    action: "exclude_legend",
    scope,
    chart_index: chartIndex,
    legend_values: values,
  });
}

/**
 * 레전드 순서·색상·Hide 오버라이드를 설정한다 (시각적, 재집계 없음).
 * order/hidden 은 통째 교체, colors 는 제공 키만 병합된다 (백엔드 규약).
 *
 * @param {number} chartIndex  현재 차트 인덱스
 * @param {{ order?: string[], colors?: Record<string,string>, hidden?: string[] }} patch
 * @param {"single"|"all"} [scope="single"]
 */
export async function setChartLegend(chartIndex, patch, scope = "single") {
  await _applyChartFilter({
    action: "set_legend",
    scope,
    chart_index: chartIndex,
    order: patch.order ?? null,
    colors: patch.colors ?? null,
    hidden: patch.hidden ?? null,
  });
}
