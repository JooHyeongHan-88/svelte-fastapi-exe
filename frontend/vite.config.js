import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import dotenv from "dotenv";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));

// 공유 상수는 프로젝트 루트의 .env 에서 로드한다 (backend/config.py 와 동기화).
dotenv.config({ path: resolve(__dirname, "../.env") });

function htmlAppName(name) {
  return {
    name: "html-app-name",
    transformIndexHtml: (html) => html.replaceAll("%APP_NAME%", name),
  };
}

export default defineConfig(() => {
  // host 는 루프백 고정 — backend/core/config.py 의 HOST 와 동일. (보안: 로컬 전용)
  const host = "127.0.0.1";
  // dev 백엔드 포트 — backend/core/config.py 의 DEV_PORT 와 동일한 APP_DEV_PORT 를 읽어
  // 프록시 타겟을 맞춘다. 운영(frozen EXE)은 OS 가 빈 포트를 동적 할당하므로 무관.
  const port = process.env.APP_DEV_PORT || "8765";
  const appName = process.env.APP_NAME || "MyAgent";

  return {
    plugins: [svelte(), htmlAppName(appName)],

    envDir: "..",

    server: {
      proxy: {
        "/api": {
          target: `http://${host}:${port}`,
          changeOrigin: true,
        },
        "/result": {
          target: `http://${host}:${port}`,
          changeOrigin: true,
        },
        "/workspace": {
          target: `http://${host}:${port}`,
          changeOrigin: true,
        },
      },
    },

    build: {
      outDir: "../build/web",
      emptyOutDir: true,
      // ECharts 번들이 ~1.1MB 로 경고 임계값을 넘으므로 허용치를 올린다.
      chunkSizeWarningLimit: 1500,
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (id.includes("echarts")) return "echarts";
          },
        },
      },
    },
  };
});
