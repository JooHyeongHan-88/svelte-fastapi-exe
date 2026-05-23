<script>
  import { onMount, onDestroy } from "svelte";
  import { initApp, teardown } from "./lib/chatActions.svelte.js";

  import Sidebar from "./components/Sidebar.svelte";
  import TopBar from "./components/TopBar.svelte";
  import ChatArea from "./components/ChatArea.svelte";
  import Composer from "./components/Composer.svelte";
  import UpdateBanner from "./components/UpdateBanner.svelte";
  import UpdateModal from "./components/UpdateModal.svelte";

  onMount(() => {
    initApp();
  });

  onDestroy(() => {
    teardown();
  });
</script>

<div class="app">
  <Sidebar />
  <main class="main">
    <TopBar />
    <ChatArea />
    <Composer />
  </main>
</div>

<UpdateBanner />
<UpdateModal />

<style>
  .app {
    display: flex;
    height: 100%;
  }

  .main {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    height: 100%;
    background: var(--bg);
  }
</style>
