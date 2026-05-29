<script>
  /**
   * 시간순 타임라인의 단일 세그먼트를 렌더하는 재귀 디스패처.
   *
   * seg.kind 에 따라 적절한 컴포넌트로 분기한다:
   *   text      → 마크다운 렌더링
   *   reasoning → ReasoningBlock (접힘/펼침 토글)
   *   tool      → ToolStep (접힘/펼침 카드)
   *   todo      → TodoProgress (항목별 expand)
   *   subagent  → SubAgentStep (재귀 중첩 타임라인)
   */

  import { renderMarkdown } from "../lib/markdown.js";
  import ReasoningBlock from "./ReasoningBlock.svelte";
  import ToolStep from "./ToolStep.svelte";
  import TodoProgress from "./TodoProgress.svelte";
  import SubAgentStep from "./SubAgentStep.svelte";

  let { seg, isStreaming = false } = $props();

  // text 세그먼트의 마크다운 렌더링
  let html = $derived(seg.kind === "text" ? renderMarkdown(seg.content ?? "") : "");

  // ReasoningBlock 용 — 스트리밍 중이고 아직 내용이 없으면 "생각 중" 애니메이션
  let reasoningStreaming = $derived(isStreaming && !(seg.content));
</script>

{#if seg.kind === "text"}
  {#if seg.content}
    <div
      class="text-seg"
      class:fallback={seg.isFallback}
      class:recovered={seg.isRecovered}
    >{@html html}</div>
  {/if}

{:else if seg.kind === "reasoning"}
  <ReasoningBlock text={seg.content ?? ""} streaming={reasoningStreaming} />

{:else if seg.kind === "tool"}
  <ToolStep {seg} />

{:else if seg.kind === "todo"}
  <TodoProgress todos={seg.todos} complete={seg.complete} />

{:else if seg.kind === "subagent"}
  <SubAgentStep {seg} {isStreaming} />
{/if}

<style>
  /* text 세그먼트 — MessageBubble 의 .markdown 과 동일한 역할 */
  .text-seg {
    /* marked + hljs 가 인라인 스타일을 생성하므로 별도 규칙 최소화 */
  }

  /* fallback: 반복 예산 소진 + 작업 미완 — 경고(빨강) */
  .text-seg.fallback {
    background-color: color-mix(in srgb, var(--danger) 5%, transparent);
    border: 1px dashed var(--danger);
    padding: 12px;
    border-radius: 8px;
    margin-top: 8px;
  }

  /* recovered: 반복 예산 소진이지만 모든 todo 완료 — 중립(초록) */
  .text-seg.recovered {
    background-color: color-mix(in srgb, var(--color-success) 8%, transparent);
    border: 1px dashed color-mix(in srgb, var(--color-success) 50%, transparent);
    padding: 12px;
    border-radius: 8px;
    margin-top: 8px;
  }
</style>
