<script>
  import { ui } from "../lib/state.svelte.js";
  import { formatElapsed } from "../lib/format.js";

  let { message } = $props();

  // ── 상황별 진행 문구 ──────────────────────────────────────────────────────
  // segments 트리를 검사해 현재 실행 중인 작업 유형을 판단한다.
  // subagent 세그먼트 내부도 재귀 검사.
  function hasRunningTool(segs) {
    for (const seg of segs ?? []) {
      if (seg.kind === "tool" && seg.status === "running") return true;
      if (seg.kind === "subagent" && hasRunningTool(seg.segments)) return true;
    }
    return false;
  }

  function hasRunningSubagent(segs) {
    for (const seg of segs ?? []) {
      if (seg.kind === "subagent" && seg.status === "running") return true;
    }
    return false;
  }

  function lastSegKind(segs) {
    if (!segs || segs.length === 0) return null;
    return segs[segs.length - 1].kind;
  }

  let statusLabel = $derived.by(() => {
    const segs = message.segments ?? [];
    if (hasRunningTool(segs)) return "도구 실행 중…";
    if (hasRunningSubagent(segs)) return "에이전트 작업 중…";
    if (lastSegKind(segs) === "reasoning") return "추론 중…";
    return "응답 생성 중…";
  });

  // ── 경과 시간 ─────────────────────────────────────────────────────────────
  // ui.nowTick 이 1초마다 갱신되므로 elapsed 가 자동으로 재계산된다.
  let elapsed = $derived(
    message.startedAt ? Math.max(0, ui.nowTick - message.startedAt) : 0,
  );
</script>

{#if message.streaming}
  <div class="turn-status" role="status" aria-live="polite" aria-label="응답 생성 중">
    <span class="pulse-dot" aria-hidden="true"></span>
    <span class="label">{statusLabel}</span>
    <span class="elapsed" aria-label="{formatElapsed(elapsed)} 경과">· {formatElapsed(elapsed)}</span>
  </div>
{/if}

<style>
  .turn-status {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin-top: 8px;
    font-size: 12px;
    color: var(--fg-muted);
    user-select: none;
  }

  /* 살아있음 표식 — 부드러운 펄스 애니메이션 */
  .pulse-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--accent);
    flex-shrink: 0;
    animation: pulse 1.8s ease-in-out infinite;
  }

  @keyframes pulse {
    0%, 100% { opacity: 0.35; transform: scale(0.82); }
    50%       { opacity: 1;    transform: scale(1); }
  }

  .label {
    color: var(--fg-muted);
    font-weight: 500;
  }

  .elapsed {
    color: var(--fg-subtle, var(--fg-muted));
    font-variant-numeric: tabular-nums;
  }
</style>
