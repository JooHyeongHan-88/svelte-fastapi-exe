<script>
  import { getArtifactPreview, artifactCsvUrl } from "../lib/api.js";

  let { payload } = $props();

  /** @type {"loading"|"ok"|"error"} */
  let status = $state("loading");
  let preview = $state(null);
  let errorMessage = $state("");
  let downloading = $state(false);

  // payload.path 가 바뀌면 (탭 전환 등) 다시 fetch.
  $effect(() => {
    const path = payload?.path;
    if (!path) {
      status = "error";
      errorMessage = "산출물 경로가 비어 있습니다.";
      return;
    }
    status = "loading";
    preview = null;
    errorMessage = "";

    getArtifactPreview(path)
      .then((data) => {
        preview = data;
        status = "ok";
      })
      .catch((err) => {
        errorMessage = String(err?.message ?? err);
        status = "error";
      });
  });

  const csvName = $derived(
    `${(payload?.filename ?? "data").replace(/\.parquet$/i, "")}.csv`,
  );

  function formatSize(bytes) {
    if (!Number.isFinite(bytes)) return "";
    const kb = bytes / 1024;
    if (kb < 1) return `${bytes}B`;
    if (kb < 1024) return `${kb.toFixed(1)}KB`;
    return `${(kb / 1024).toFixed(2)}MB`;
  }

  async function downloadCsv() {
    if (downloading) return;
    downloading = true;
    try {
      const url = artifactCsvUrl(payload.path);
      // Chromium 계열: 저장 위치 선택 다이얼로그 + 스트리밍 저장.
      if (typeof window.showSaveFilePicker === "function") {
        try {
          const handle = await window.showSaveFilePicker({
            suggestedName: csvName,
            types: [{ description: "CSV", accept: { "text/csv": [".csv"] } }],
          });
          const res = await fetch(url);
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const writable = await handle.createWritable();
          await res.body.pipeTo(writable); // pipeTo 가 완료 시 writable 을 닫는다.
          return;
        } catch (err) {
          if (err?.name === "AbortError") return; // 사용자가 다이얼로그를 취소
          console.error("save picker 실패 — 앵커 다운로드로 폴백:", err);
        }
      }
      // 미지원 브라우저/실패 폴백 — 브라우저 기본 다운로드 경로.
      const a = document.createElement("a");
      a.href = url;
      a.download = csvName;
      document.body.appendChild(a);
      a.click();
      a.remove();
    } finally {
      downloading = false;
    }
  }
</script>

<div class="artifact-data-wrap">
  <div class="toolbar">
    <span class="data-label">{payload?.filename || "데이터"}</span>
    <button
      class="csv-btn"
      onclick={downloadCsv}
      disabled={downloading || status !== "ok"}
      title="전체 데이터를 CSV 파일로 저장"
    >
      <svg
        width="14"
        height="14"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        stroke-width="1.8"
      >
        <path d="M8 2v8M4.5 6.5 8 10l3.5-3.5M3 13h10" />
      </svg>
      {downloading ? "저장 중..." : "CSV 저장"}
    </button>
  </div>

  <div class="data-body">
    {#if status === "loading"}
      <div class="loading">불러오는 중...</div>
    {:else if status === "error"}
      <div class="artifact-error">
        <strong>데이터를 불러올 수 없습니다.</strong>
        <span class="reason">{errorMessage}</span>
      </div>
    {:else}
      <div class="meta-line">
        <span class="meta-strong">
          {preview.total_rows.toLocaleString()} rows × {preview.schema.length} cols
        </span>
        <span class="meta-dim">· {formatSize(preview.size)}</span>
      </div>
      <div class="path-line" title={preview.path}>{preview.path}</div>

      <div class="caption">상위 {preview.head.rows.length}행 미리보기</div>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              {#each preview.head.columns as col, i (col)}
                <th>
                  <div class="col-name">{col}</div>
                  <div class="col-dtype">{preview.schema[i]?.dtype ?? ""}</div>
                </th>
              {/each}
            </tr>
          </thead>
          <tbody>
            {#each preview.head.rows as row, ri (ri)}
              <tr>
                {#each row as cell, ci (ci)}
                  <td>
                    {#if cell === null}
                      <span class="null-cell">null</span>
                    {:else}
                      {cell}
                    {/if}
                  </td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </div>
</div>

<style>
  .artifact-data-wrap {
    display: flex;
    flex-direction: column;
    height: 100%;
  }

  .toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 14px;
    border-bottom: 1px solid var(--border);
    background: var(--bg-elevated);
    flex-shrink: 0;
  }

  .data-label {
    font-size: 12px;
    color: var(--fg-muted);
    font-family: var(--font-mono, monospace);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 60%;
  }

  .csv-btn {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 11px;
    font-weight: 500;
    color: var(--accent);
    background: color-mix(in srgb, var(--accent) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent) 25%, transparent);
    border-radius: var(--radius-sm);
    padding: 3px 9px;
    cursor: pointer;
    transition: background 0.15s;
    flex-shrink: 0;
  }

  .csv-btn:hover:not(:disabled) {
    background: color-mix(in srgb, var(--accent) 20%, transparent);
  }

  .csv-btn:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .data-body {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    padding: 14px 16px;
    min-height: 0;
    gap: 4px;
  }

  .meta-line {
    font-size: 13px;
    color: var(--fg);
  }

  .meta-strong {
    font-weight: 600;
  }

  .meta-dim {
    color: var(--fg-muted);
  }

  .path-line {
    font-size: 11px;
    color: var(--fg-muted);
    font-family: var(--font-mono, monospace);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .caption {
    margin-top: 8px;
    font-size: 11px;
    color: var(--fg-muted);
  }

  /* 컬럼이 많은 중간 데이터 대응 — 횡 스크롤 필수. */
  .table-scroll {
    flex: 1;
    overflow: auto;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    min-height: 0;
  }

  table {
    border-collapse: collapse;
    font-size: 12px;
    width: max-content;
    min-width: 100%;
  }

  th,
  td {
    border-bottom: 1px solid var(--border);
    padding: 5px 10px;
    text-align: left;
    white-space: nowrap;
    max-width: 240px;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  th {
    position: sticky;
    top: 0;
    background: var(--bg-elevated);
    z-index: 1;
  }

  .col-name {
    font-weight: 600;
    color: var(--fg);
  }

  .col-dtype {
    font-weight: 400;
    font-size: 10px;
    color: var(--fg-muted);
    font-family: var(--font-mono, monospace);
  }

  td {
    color: var(--fg);
    font-family: var(--font-mono, monospace);
  }

  .null-cell {
    color: var(--fg-muted);
    font-style: italic;
  }

  .loading {
    color: var(--fg-muted);
    font-size: 13px;
    text-align: center;
    padding-top: 32px;
  }

  .artifact-error {
    margin: 24px auto;
    max-width: 360px;
    padding: 14px 16px;
    border: 1px dashed var(--danger, #d33);
    border-radius: var(--radius-md);
    color: var(--danger, #d33);
    background: color-mix(in srgb, var(--danger, #d33) 7%, transparent);
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
