<script>
  /**
   * 아티팩트 종류별 인라인 SVG 아이콘 (lucide풍 stroke).
   * 이모지(🖼️📊📝🗂️📄) 대체 — 오프라인 안전 + currentColor 상속으로 테마 일관성.
   * kind: "image" | "chart" | "markdown" | "data" | "extension" | 그 외(file 폴백)
   */
  let { kind = "file", size = 13 } = $props();
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="2"
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
>
  {#if kind === "image"}
    <rect x="3" y="3" width="18" height="18" rx="2" />
    <circle cx="9" cy="9" r="2" />
    <path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" />
  {:else if kind === "chart"}
    <path d="M3 3v18h18" />
    <path d="M18 17V9" />
    <path d="M13 17V5" />
    <path d="M8 17v-3" />
  {:else if kind === "markdown"}
    <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
    <path d="M14 2v4a2 2 0 0 0 2 2h4" />
    <path d="M16 13H8" />
    <path d="M16 17H8" />
  {:else if kind === "data"}
    <ellipse cx="12" cy="5" rx="9" ry="3" />
    <path d="M3 5v14a9 3 0 0 0 18 0V5" />
    <path d="M3 12a9 3 0 0 0 18 0" />
  {:else if kind === "extension"}
    <!-- 퍼즐 조각 — 확장(extension) -->
    <path
      d="M9.5 3.5a1.5 1.5 0 0 1 3 0c0 .8.7 1 1.5 1H16a1 1 0 0 1 1 1v1.5c0 .8.2 1.5 1 1.5a1.5 1.5 0 0 1 0 3c-.8 0-1 .7-1 1.5V18a1 1 0 0 1-1 1h-1.5c-.8 0-1.5.2-1.5 1a1.5 1.5 0 0 1-3 0c0-.8-.7-1-1.5-1H6a1 1 0 0 1-1-1v-2c0-.8-.7-1-1.5-1a1.5 1.5 0 0 1 0-3c.8 0 1.5-.2 1.5-1V6a1 1 0 0 1 1-1h2c.8 0 1.5-.2 1.5-1Z"
    />
  {:else}
    <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
    <path d="M14 2v4a2 2 0 0 0 2 2h4" />
  {/if}
</svg>

<style>
  svg {
    flex-shrink: 0;
  }
</style>
