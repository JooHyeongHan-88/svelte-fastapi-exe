<script>
  import { onMount } from "svelte";

  let input = "";
  let messages = [];

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

    messages = [...messages, { role: "assistant",  content: data.message }];
  }

  onMount(async () => {
    // register
    await fetch("/api/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client_id: clientId }),
    });

    // heartbeat
    const interval = setInterval(
      async () => {
        try {
          await fetch(
            "/api/heartbeat",
            {
              method: "POST",
              keepalive: true,
              headers: { "Content-Type":  "application/json" },
              body: JSON.stringify({ client_id:  clientId })
            }
          );
        } catch {
          // ignore
        }
      },
      5000
    );

    // unregister on close
    const onUnload = () => {
      navigator.sendBeacon(
        "/api/unregister",
        JSON.stringify({  client_id: clientId })
      );
    };

    window.addEventListener("unload", onUnload);

    return () => {
      clearInterval(interval);

      window.removeEventListener("unload", onUnload);
    };
  });
</script>

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
    onkeydown={ (e) => e.key === "Enter" && sendMessage() }
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
</style>