<script>
  import { onMount } from "svelte";

  let input = "";
  let messages = [];

  let updateInfo = null; // { current, latest, update_available, notes, size }
  let updateDismissed = false;
  let modalOpen = false;
  let applying = false;
  let applyState = null; // { status, progress, total, message, target_version }
  let restarting = false;

  function getClientId() {
    let id = sessionStorage.getItem("client_id");

    if (!id) {
      id = crypto.randomUUID();
      sessionStorage.setItem("client_id", id);
    }

    return id;
  }

  const clientId = getClientId();

  async function sendMessage() {
    if (!input.trim()) return;

    const userMessage = input;

    messages = [...messages, { role: "user", content: userMessage }];

    input = "";

    const response = await fetch(
      "/api/chat",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMessage }),
      }
    );

    const data = await response.json();

    messages = [...messages, { role: "assistant", content: data.message }];
  }

  function postJson(url, payload) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  function checkUpdate() {
    fetch("/api/update/check")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!data) return;

        updateInfo = data;

        const dismissedFor = sessionStorage.getItem("update_dismissed_for");
        if (dismissedFor && dismissedFor === data.latest) {
          updateDismissed = true;
        }
      })
      .catch(() => {});
  }

  function dismissUpdate() {
    updateDismissed = true;
    if (updateInfo?.latest) {
      sessionStorage.setItem("update_dismissed_for", updateInfo.latest);
    }
  }

  async function applyUpdate() {
    applying = true;
    applyState = { status: "starting", progress: 0, total: 0, message: "" };
    modalOpen = true;

    const pollId = setInterval(async () => {
      try {
        const r = await fetch("/api/update/status");
        if (r.ok) {
          applyState = await r.json();
        }
      } catch {
        // 서버가 내려가는 중일 수 있음 — restarting 단계로 전환
        clearInterval(pollId);
        restarting = true;
      }
    }, 500);

    try {
      const r = await postJson("/api/update/apply", {});
      const data = await r.json();
      if (!data.ok) {
        clearInterval(pollId);
        applying = false;
        applyState = { status: "error", message: data.error || "unknown" };
      }
    } catch (e) {
      clearInterval(pollId);
      applying = false;
      applyState = { status: "error", message: String(e) };
    }
  }

  function progressPct(s) {
    if (!s || !s.total) return 0;
    return Math.min(100, Math.round((s.progress / s.total) * 100));
  }

  onMount(() => {
    postJson("/api/register", { client_id: clientId }).catch(() => {});

    checkUpdate();

    const heartbeat = setInterval(() => {
      fetch("/api/heartbeat", {
        method: "POST",
        keepalive: true,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ client_id: clientId }),
      }).catch(() => {});
    }, 5000);

    const onPageHide = () => {
      const blob = new Blob(
        [JSON.stringify({ client_id: clientId })],
        { type: "application/json" },
      );
      navigator.sendBeacon("/api/unregister", blob);
    };

    window.addEventListener("pagehide", onPageHide);

    return () => {
      clearInterval(heartbeat);
      window.removeEventListener("pagehide", onPageHide);
    };
  });
</script>

{#if updateInfo?.update_available && !updateDismissed && !modalOpen}
  <div class="update-banner">
    <span>새 버전 <b>{updateInfo.latest}</b> 사용 가능 (현재 {updateInfo.current})</span>
    <button onclick={applyUpdate}>지금 업데이트</button>
    <button class="ghost" onclick={dismissUpdate}>나중에</button>
  </div>
{/if}

{#if modalOpen}
  <div class="modal-backdrop">
    <div class="modal">
      {#if restarting}
        <h3>재시작 중…</h3>
        <p>새 버전으로 교체 후 자동으로 다시 열립니다.</p>
      {:else if applyState?.status === "error"}
        <h3>업데이트 실패</h3>
        <p>{applyState.message}</p>
        <button onclick={() => { modalOpen = false; applying = false; }}>닫기</button>
      {:else}
        <h3>업데이트 진행 중</h3>
        <p>{applyState?.message ?? ""}</p>
        <div class="progress">
          <div class="bar" style="width: {progressPct(applyState)}%"></div>
        </div>
        <small>{applyState?.status ?? ""}</small>
      {/if}
    </div>
  </div>
{/if}

<h1>My Agent</h1>

<div class="chat">
  {#each messages as msg}
    <div class={msg.role}>
      <b>{msg.role}</b>: {msg.content}
    </div>
  {/each}
</div>

<div class="input-row">
  <input
    bind:value={input}
    onkeydown={(e) => e.key === "Enter" && sendMessage()}
    placeholder="message..."
  />

  <button onclick={sendMessage}>
    Send
  </button>
</div>

<style>
  .chat {
    margin-bottom: 1rem;
  }

  .user,
  .assistant {
    margin: 8px 0;
  }

  .input-row {
    display: flex;
    gap: 8px;
  }

  input {
    flex: 1;
  }

  .update-banner {
    position: fixed;
    top: 12px;
    right: 12px;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background: #1f6feb;
    color: white;
    border-radius: 6px;
    font-size: 0.9rem;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  }

  .update-banner button {
    padding: 4px 10px;
    border: none;
    border-radius: 4px;
    background: white;
    color: #1f6feb;
    cursor: pointer;
  }

  .update-banner button.ghost {
    background: transparent;
    color: white;
    border: 1px solid rgba(255, 255, 255, 0.6);
  }

  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.45);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 10;
  }

  .modal {
    background: white;
    color: #111;
    padding: 24px;
    border-radius: 8px;
    min-width: 320px;
    max-width: 480px;
  }

  .progress {
    width: 100%;
    height: 8px;
    background: #eee;
    border-radius: 4px;
    overflow: hidden;
    margin: 12px 0 4px;
  }

  .bar {
    height: 100%;
    background: #1f6feb;
    transition: width 0.2s ease;
  }
</style>
