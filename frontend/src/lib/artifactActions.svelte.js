// 아티팩트 패널 액션 — display_image / display_chart / display_markdown 결과 관리.
//
// 영속화 모델: payload 는 ui.* 휘발 상태가 아니라 메시지의 artifactChips 안에 통째로
// 임베드된다. localStorage 가 메시지를 직렬화할 때 자연스럽게 함께 보존되므로,
// 세션을 나갔다 다시 들어와도 칩을 클릭하면 동일 산출물이 패널에 다시 표시된다.

import { ui, activeSession } from "./state.svelte.js";

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
}

/** 패널 닫기 (칩은 메시지에 그대로 — 다시 클릭하면 열림). */
export function closeArtifactPanel() {
  ui.artifactPanelOpen = false;
}

/** 패널 토글. */
export function toggleArtifactPanel() {
  ui.artifactPanelOpen = !ui.artifactPanelOpen;
}

/**
 * 세션 전환 시 패널 가시성 / 활성 id 만 리셋한다.
 * payload 는 메시지에 영속되므로 비울 게 없다.
 */
export function resetArtifactPanelState() {
  ui.activeArtifactId = null;
  ui.artifactPanelOpen = false;
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
    return payload.alt || payload.caption || "이미지";
  }
  if (kind === "chart") {
    const typeLabel = {
      scatter: "산점도",
      line: "꺾은선",
      bar: "막대",
      histogram: "히스토그램",
      box: "박스플롯",
      heatmap: "히트맵",
    };
    const t = typeLabel[payload.chart_type] || "차트";
    return payload.title || t;
  }
  if (kind === "markdown") {
    return payload.title || "마크다운 문서";
  }
  return "아티팩트";
}
