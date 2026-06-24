import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import dotenv from "dotenv";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));

// 프로젝트 루트 .env 에서 dev 백엔드 포트를 읽어 프록시 타겟을 맞춘다.
// frontend → tracer → extensions → project_root
dotenv.config({ path: resolve(__dirname, "../../../.env") });

export default defineConfig(() => {
  const host = "127.0.0.1";
  const port = process.env.APP_DEV_PORT || "8765";

  return {
    plugins: [svelte()],

    // 백엔드가 /ext/tracer 로 정적 서빙하므로 자산 경로 기준을 맞춘다.
    base: "/ext/tracer/",

    server: {
      // 메인(5173)·evaluator(5174)와 분리. dev 시 백엔드로 /api·/result 프록시.
      port: 5175,
      proxy: {
        "/api": { target: `http://${host}:${port}`, changeOrigin: true },
        "/result": { target: `http://${host}:${port}`, changeOrigin: true },
      },
    },

    build: {
      outDir: "dist",
      emptyOutDir: true,
      chunkSizeWarningLimit: 1500,
    },
  };
});
