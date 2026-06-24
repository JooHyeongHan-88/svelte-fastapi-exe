// 메인 앱(호스트)과 테마를 동기화한다. iframe 은 부모 문서의 CSS 변수를 상속하지
// 않으므로, 확장이 스스로 documentElement 에 data-theme 를 적용해야 한다.
//
//   초기값: 호스트가 iframe src 에 붙여준 ?theme= 쿼리 (ArtifactExtension.svelte).
//   변경:   호스트 setTheme 가 BroadcastChannel("app:theme") 로 방송 → 여기서 수신.

export const themeState = $state({ name: "light" });

function normalize(name) {
  return name === "dark" ? "dark" : "light";
}

export function applyTheme(name) {
  const t = normalize(name);
  themeState.name = t;
  document.documentElement.setAttribute("data-theme", t);
}

let channel = null;

/** 앱 부팅 시 1회 호출 — URL 쿼리로 초기 테마 적용 + 호스트 방송 구독. */
export function initTheme() {
  try {
    const q = new URLSearchParams(window.location.search);
    applyTheme(q.get("theme") || "light");
  } catch {
    applyTheme("light");
  }

  if (channel || typeof BroadcastChannel === "undefined") return;
  try {
    channel = new BroadcastChannel("app:theme");
    channel.onmessage = (event) => {
      const msg = event?.data;
      if (msg && msg.type === "theme") applyTheme(msg.theme);
    };
  } catch {
    channel = null; // 미지원 환경 — 초기 테마만 적용(라이브 동기화 없음).
  }
}
