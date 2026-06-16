<script>
  import { untrack } from "svelte";
  import { ui } from "../lib/state.svelte.js";

  // 확장(extension) SPA 를 우측 패널에 iframe 으로 임베드한다. evaluator 처럼 격리된
  // 빌드 SPA 를 그대로 재사용하므로 same-origin iframe 이 유일하게 합리적인 임베드
  // 방식이다 — base="/ext/<tool>/" 라 iframe 안의 에셋·/api/ext 호출이 same-origin 으로
  // 동작하고 Origin 가드도 통과한다. sandbox 는 지정하지 않는다(같은 출처 XHR 필요).
  let { payload } = $props();

  // 메인 앱 테마를 확장 iframe 에 URL 쿼리로 전달한다(초기 로드 정합). iframe 로드 시점의
  // 현재 테마를 읽되, 테마 변경만으로는 src 가 바뀌지 않도록 untrack 으로 비반응 읽기를 한다 —
  // 테마 토글 시 iframe 리로드(상태 소실)를 피하고, 라이브 변경은 확장이 BroadcastChannel
  // ("app:theme")로 직접 수신한다. payload.src 가 바뀔 때(탭 전환)만 현재 테마로 재계산된다.
  function withTheme(src, theme) {
    if (!src) return src;
    const sep = src.includes("?") ? "&" : "?";
    return `${src}${sep}theme=${encodeURIComponent(theme)}`;
  }

  const frameSrc = $derived.by(() =>
    withTheme(payload?.src, untrack(() => ui.theme)),
  );
</script>

<div class="artifact-ext-wrap">
  {#if payload?.src}
    <iframe
      class="ext-frame"
      src={frameSrc}
      title={payload?.title || payload?.tool || "확장 도구"}
    ></iframe>
  {:else}
    <div class="artifact-error">
      <strong>확장을 불러올 수 없습니다.</strong>
      <span class="reason">src 경로가 비어 있습니다.</span>
    </div>
  {/if}
</div>

<style>
  .artifact-ext-wrap {
    display: flex;
    flex-direction: column;
    height: 100%;
  }

  .ext-frame {
    flex: 1;
    width: 100%;
    height: 100%;
    border: 0;
    background: var(--bg);
  }

  .artifact-error {
    margin: 24px auto;
    max-width: 360px;
    padding: 14px 16px;
    border: 1px dashed var(--danger);
    border-radius: var(--radius-md);
    color: var(--danger);
    background: color-mix(in srgb, var(--danger) 7%, transparent);
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: 13px;
    text-align: center;
  }

  .artifact-error .reason {
    font-size: 11px;
    opacity: 0.8;
    font-family: var(--font-mono, monospace);
  }
</style>
