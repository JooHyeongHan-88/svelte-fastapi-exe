import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import dotenv from "dotenv";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));

// 공유 상수는 프로젝트 루트의 .env 에서 로드한다 (backend/config.py 와 동기화).
dotenv.config({ path: resolve(__dirname, "../.env") });

export default defineConfig(() => {
  const host = process.env.APP_HOST || "127.0.0.1";
  const port = process.env.APP_PORT || "8765";

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
