// 아티팩트 패널 액션 — display_image / display_chart 도구 결과 관리

import { ui } from "./state.svelte.js";

/**
 * 새 아티팩트를 추가하고 패널을 연다.
 *
 * @param {"image"|"chart"} kind
 * @param {object} payload  - ToolResultEvent.data (kind 필드 포함)
 * @param {string|null} sourceMessageId - 해당 도구 결과가 포함된 메시지 id
 * @returns {string} 생성된 아티팩트 id
 */
export function addArtifact(kind, payload, sourceMessageId = null) {
  const id = `artifact-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const label = _artifactLabel(kind, payload);

  ui.artifacts.push({
    id,
    kind,
    payload,
    label,
    sourceMessageId,
    createdAt: Date.now(),
  });

  ui.activeArtifactId = id;
  ui.artifactPanelOpen = true;

  return id;
}

/**
 * 특정 아티팩트를 활성화(패널이 닫혀 있으면 열기).
 * @param {string} id
 */
export function openArtifact(id) {
  const found = ui.artifacts.find((a) => a.id === id);
  if (!found) return;
  ui.activeArtifactId = id;
  ui.artifactPanelOpen = true;
}

/** 패널 닫기 (아티팩트 목록은 유지). */
export function closeArtifactPanel() {
  ui.artifactPanelOpen = false;
}

/** 패널 토글. */
export function toggleArtifactPanel() {
  ui.artifactPanelOpen = !ui.artifactPanelOpen;
}

/**
 * 세션 전환 시 아티팩트 목록 초기화.
 * (MVP: 세션 단위 휘발. 히스토리 복원 시 재구성 대상 아님.)
 */
export function clearArtifacts() {
  ui.artifacts = [];
  ui.activeArtifactId = null;
  ui.artifactPanelOpen = false;
}

// ---------------------------------------------------------------------------
// 내부 헬퍼
// ---------------------------------------------------------------------------

function _artifactLabel(kind, payload) {
  if (kind === "image") {
    return payload.alt || payload.caption || "이미지";
  }
  if (kind === "chart") {
    const typeLabel = { scatter: "산점도", line: "꺾은선", bar: "막대", histogram: "히스토그램", box: "박스플롯", heatmap: "히트맵" };
    const t = typeLabel[payload.chart_type] || "차트";
    return payload.title || t;
  }
  return "아티팩트";
}
