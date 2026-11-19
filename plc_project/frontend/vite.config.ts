import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
        processos: resolve(__dirname, "processos.html"),
      },
      output: {
        // Keep ELK's generated parser out of the entry chunk scanned for dynamic imports.
        manualChunks: { elk: ["elkjs/lib/elk.bundled.js"] },
      },
    },
  },
  server: {
    port: 5173,
    host: "127.0.0.1",
    // api.ts 在 DEV 下 GATEWAY_BASE 为空时走同源；代理到本机网关
    proxy: {
      "/api/processos": { target: "http://127.0.0.1:8010", changeOrigin: true },
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/health": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
