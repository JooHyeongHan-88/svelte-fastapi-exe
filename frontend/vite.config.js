import { defineConfig, loadEnv } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// 공유 상수는 프로젝트 루트의 .env 에서 로드한다 (backend/config.py 와 동기화).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "..", "APP_");
  const host = env.APP_HOST || "127.0.0.1";
  const port = env.APP_PORT || "8765";

  return {
    plugins: [svelte()],

    envDir: "..",

    server: {
      proxy: {
        "/api": {
          target: `http://${host}:${port}`,
          changeOrigin: true,
        },
      },
    },

    build: {
      outDir: "../build/web",
      emptyOutDir: true,
    },
  };
});
