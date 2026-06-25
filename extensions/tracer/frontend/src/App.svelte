<script>
  import { onMount } from "svelte";
  import { getSessions, getTurns, getTrace } from "./lib/api.js";

  // view: "sessions" | "turns" | "timeline"
  let view = $state("sessions");
  let loading = $state(true);
  let error = $state("");

  let sessions = $state([]);
  let turns = $state([]);
  let events = $state([]);
  let skipped = $state(0);

  let activeSession = $state("");
  let activeTurn = $state("");

  // 타임라인 필터
  let agentFilter = $state("");
  let kindFilter = $state("");

  const KIND_LABELS = {
    turn_start: "턴 시작",
    provider_request: "→ LLM 요청",
    provider_response: "← LLM 응답",
    sentinel_route: "sentinel",
    tool_result: "도구 결과",
    slot_guard: "슬롯 가드",
    malformed_args: "깨진 인자",
    loop_guard: "루프 가드",
    wind_down: "wind-down",
    budget_exhausted: "예산 소진",
    max_iter_fallback: "반복 상한",
    turn_end: "턴 종료",
    turn_error: "턴 오류",
  };

  function kindClass(ev) {
    const k = ev.kind;
    if (k === "turn_error" || k === "budget_exhausted" || k === "max_iter_fallback")
      return "danger";
    if (k === "loop_guard") return ev.payload?.blocked ? "danger" : "neutral";
    if (k === "slot_guard" || k === "malformed_args" || k === "wind_down")
      return "warn";
    if (k === "provider_request" || k === "provider_response") return "io";
    return "neutral";
  }

  const agents = $derived([...new Set(events.map((e) => e.agent_id || ""))]);
  const kinds = $derived([...new Set(events.map((e) => e.kind))]);
  const filtered = $derived(
    events.filter(
      (e) =>
        (!agentFilter || e.agent_id === agentFilter) &&
        (!kindFilter || e.kind === kindFilter),
    ),
  );

  function fmtTime(epoch) {
    try {
      return new Date(epoch * 1000).toLocaleString();
    } catch {
      return String(epoch);
    }
  }

  function fmtSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }

  async function loadSessions() {
    loading = true;
    error = "";
    try {
      sessions = await getSessions();
      view = "sessions";
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  async function openSession(session) {
    loading = true;
    error = "";
    activeSession = session;
    try {
      turns = await getTurns(session);
      view = "turns";
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  async function openTurn(turn) {
    loading = true;
    error = "";
    activeTurn = turn.name;
    agentFilter = "";
    kindFilter = "";
    try {
      const res = await getTrace(turn.path);
      events = res.events || [];
      skipped = res.skipped || 0;
      view = "timeline";
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  onMount(loadSessions);
</script>

<div class="app">
  <header class="top">
    <div class="crumbs">
      <button class="link" onclick={loadSessions}>세션</button>
      {#if activeSession && view !== "sessions"}
        <span class="sep">/</span>
        <button class="link" onclick={() => openSession(activeSession)}>
          {activeSession}
        </button>
      {/if}
      {#if view === "timeline"}
        <span class="sep">/</span>
        <span class="cur">{activeTurn}</span>
      {/if}
    </div>
    <div class="title">🔍 Tracer <span class="dim">디버그 트레이스</span></div>
  </header>

  {#if error}
    <div class="banner err">{error}</div>
  {/if}

  {#if loading}
    <div class="empty">불러오는 중…</div>
  {:else if view === "sessions"}
    {#if sessions.length === 0}
      <div class="empty">
        <p>트레이스가 없습니다.</p>
        <p class="dim">
          dev 환경에서 <code>APP_DEBUG_TRACE=true</code> 로 실행한 뒤 에이전트와
          대화하면 턴마다 트레이스가 기록됩니다.
        </p>
      </div>
    {:else}
      <div class="list">
        {#each sessions as s (s.session)}
          <button class="row" onclick={() => openSession(s.session)}>
            <span class="row-main">{s.session}</span>
            <span class="row-meta">{s.turns}턴 · {fmtTime(s.latest)}</span>
          </button>
        {/each}
      </div>
    {/if}
  {:else if view === "turns"}
    {#if turns.length === 0}
      <div class="empty">이 세션에 턴 트레이스가 없습니다.</div>
    {:else}
      <div class="list">
        {#each turns as t (t.path)}
          <button class="row" onclick={() => openTurn(t)}>
            <span class="row-main" class:preview={t.preview}>{t.preview || t.name}</span>
            <span class="row-meta">{fmtTime(t.mtime)} · {fmtSize(t.size)}</span>
          </button>
        {/each}
      </div>
    {/if}
  {:else if view === "timeline"}
    <div class="filters">
      <label>
        에이전트
        <select bind:value={agentFilter}>
          <option value="">전체</option>
          {#each agents as a (a)}
            <option value={a}>{a || "(orchestrator)"}</option>
          {/each}
        </select>
      </label>
      <label>
        종류
        <select bind:value={kindFilter}>
          <option value="">전체</option>
          {#each kinds as k (k)}
            <option value={k}>{KIND_LABELS[k] || k}</option>
          {/each}
        </select>
      </label>
      <span class="count">
        {filtered.length} / {events.length} 이벤트
        {#if skipped}· <span class="warn-t">{skipped}줄 손상</span>{/if}
      </span>
    </div>

    <div class="timeline">
      {#each filtered as ev, i (i)}
        <div class="event {kindClass(ev)}">
          <div class="ev-head">
            <span class="ev-kind">{KIND_LABELS[ev.kind] || ev.kind}</span>
            <span class="ev-scope">
              {ev.agent_id || "orchestrator"}
              {#if ev.depth}<span class="depth">·d{ev.depth}</span>{/if}
              {#if ev.iteration != null}<span class="iter">·#{ev.iteration}</span
                >{/if}
            </span>
            <span class="ev-ts">{ev.ts?.split("T")[1] ?? ""}</span>
          </div>

          {#if ev.kind === "provider_request"}
            <div class="ev-body">
              <div class="kv">
                <span class="k">model</span><span class="v">{ev.payload.model}</span>
              </div>
              {#if ev.payload.tools?.length}
                <div class="chips">
                  {#each ev.payload.tools as tn (tn)}
                    <span class="chip">{tn}</span>
                  {/each}
                </div>
              {/if}
              <details>
                <summary>messages ({ev.payload.messages?.length ?? 0})</summary>
                {#each ev.payload.messages ?? [] as m (m)}
                  <div class="msg">
                    <span class="role {m.role}">{m.role}</span>
                    {#if m.content}<pre class="content">{m.content}</pre>{/if}
                    {#if m.tool_calls?.length}
                      {#each m.tool_calls as tc (tc.id)}
                        <div class="toolcall">
                          ⚙ {tc.name}
                          <pre>{JSON.stringify(tc.arguments, null, 2)}</pre>
                        </div>
                      {/each}
                    {/if}
                  </div>
                {/each}
              </details>
            </div>
          {:else if ev.kind === "provider_response"}
            <div class="ev-body">
              {#if ev.payload.finish_reason}
                <div class="kv">
                  <span class="k">finish</span>
                  <span class="v badge">{ev.payload.finish_reason}</span>
                </div>
              {/if}
              {#if ev.payload.reasoning}
                <details>
                  <summary>reasoning</summary>
                  <pre class="content dim">{ev.payload.reasoning}</pre>
                </details>
              {/if}
              {#if ev.payload.text}<pre class="content">{ev.payload.text}</pre>{/if}
              {#if ev.payload.tool_calls?.length}
                {#each ev.payload.tool_calls as tc (tc.id)}
                  <div class="toolcall">
                    ⚙ {tc.name}
                    <pre>{JSON.stringify(tc.arguments, null, 2)}</pre>
                  </div>
                {/each}
              {/if}
            </div>
          {:else}
            <div class="ev-body">
              <pre class="content">{JSON.stringify(ev.payload, null, 2)}</pre>
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .app {
    display: flex;
    flex-direction: column;
    height: 100vh;
    overflow: hidden;
  }
  .top {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 16px;
    border-bottom: 1px solid var(--border);
    background: var(--panel);
  }
  .crumbs {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    overflow: hidden;
  }
  .link {
    background: none;
    border: none;
    color: var(--accent);
    padding: 2px 4px;
    border-radius: var(--radius-sm);
  }
  .link:hover {
    background: var(--accent-soft);
  }
  .sep {
    color: var(--subtle);
  }
  .cur {
    color: var(--fg);
    font-family: var(--mono);
    font-size: 13px;
  }
  .title {
    font-weight: 600;
  }
  .title .dim,
  .dim {
    color: var(--muted);
    font-weight: 400;
  }
  .banner.err {
    margin: 10px 16px;
    padding: 8px 12px;
    border-radius: var(--radius-sm);
    background: color-mix(in srgb, var(--danger) 14%, transparent);
    color: var(--danger);
  }
  .empty {
    padding: 48px 24px;
    text-align: center;
    color: var(--muted);
  }
  .empty code {
    font-family: var(--mono);
    background: var(--panel-2);
    padding: 1px 6px;
    border-radius: 4px;
  }
  .list {
    overflow: auto;
    padding: 12px 16px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    width: 100%;
    text-align: left;
    padding: 10px 14px;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--panel);
    color: var(--fg);
  }
  .row:hover {
    border-color: var(--accent-border);
    background: var(--accent-soft);
  }
  .row-main {
    font-family: var(--mono);
    font-size: 13px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  /* 자연어 쿼리 미리보기는 가독성 위해 sans 폰트 (폴백 턴 ID 는 mono 유지) */
  .row-main.preview {
    font-family: inherit;
  }
  .row-meta {
    flex: 0 0 auto;
    color: var(--muted);
    font-size: 12px;
  }
  .filters {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 10px 16px;
    border-bottom: 1px solid var(--border);
    background: var(--panel-2);
  }
  .filters label {
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--muted);
    font-size: 13px;
  }
  .filters select {
    font-family: inherit;
    font-size: 13px;
    padding: 3px 6px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--panel);
    color: var(--fg);
  }
  .count {
    margin-left: auto;
    color: var(--muted);
    font-size: 12px;
  }
  .warn-t {
    color: var(--warn);
  }
  .timeline {
    overflow: auto;
    padding: 12px 16px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .event {
    border: 1px solid var(--border);
    border-left: 3px solid var(--subtle);
    border-radius: var(--radius-sm);
    background: var(--panel);
    padding: 8px 12px;
  }
  .event.io {
    border-left-color: var(--accent);
  }
  .event.warn {
    border-left-color: var(--warn);
  }
  .event.danger {
    border-left-color: var(--danger);
  }
  .ev-head {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 12px;
  }
  .ev-kind {
    font-weight: 600;
  }
  .ev-scope {
    color: var(--muted);
    font-family: var(--mono);
  }
  .depth,
  .iter {
    color: var(--subtle);
  }
  .ev-ts {
    margin-left: auto;
    color: var(--subtle);
    font-family: var(--mono);
  }
  .ev-body {
    margin-top: 6px;
  }
  .kv {
    display: flex;
    gap: 8px;
    font-size: 12px;
    margin-bottom: 4px;
  }
  .kv .k {
    color: var(--muted);
    font-family: var(--mono);
  }
  .badge {
    background: var(--panel-2);
    padding: 0 6px;
    border-radius: 4px;
    font-family: var(--mono);
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-bottom: 4px;
  }
  .chip {
    font-size: 11px;
    font-family: var(--mono);
    background: var(--panel-2);
    color: var(--muted);
    padding: 1px 6px;
    border-radius: 4px;
  }
  details summary {
    cursor: pointer;
    color: var(--accent);
    font-size: 12px;
    margin: 4px 0;
  }
  .msg {
    border-top: 1px dashed var(--border);
    padding: 6px 0;
  }
  .role {
    display: inline-block;
    font-size: 11px;
    font-family: var(--mono);
    padding: 0 6px;
    border-radius: 4px;
    background: var(--panel-2);
    color: var(--muted);
    margin-bottom: 4px;
  }
  .role.system {
    color: var(--warn);
  }
  .role.assistant {
    color: var(--accent);
  }
  .role.tool {
    color: var(--success);
  }
  pre.content {
    margin: 4px 0;
    padding: 8px;
    background: var(--panel-2);
    border-radius: var(--radius-sm);
    font-family: var(--mono);
    font-size: 12px;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 320px;
    overflow: auto;
  }
  .toolcall {
    margin: 4px 0;
    font-family: var(--mono);
    font-size: 12px;
    color: var(--accent);
  }
  .toolcall pre {
    margin: 2px 0 0;
    padding: 6px;
    background: var(--panel-2);
    border-radius: var(--radius-sm);
    color: var(--fg);
    white-space: pre-wrap;
    word-break: break-word;
  }
</style>
