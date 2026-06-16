import { mount } from "svelte";
import App from "./App.svelte";
import { initTheme } from "./lib/theme.svelte.js";
import "./app.css";

// 호스트 테마(다크/라이트) 동기화 — mount 전에 적용해 첫 페인트부터 일치시킨다.
initTheme();

const app = mount(App, {
  target: document.getElementById("app"),
});

export default app;
