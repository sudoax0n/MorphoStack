import { defineConfig } from "vite";

const apiTarget = process.env.MORPHOSTACK_API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
        // Large microscopy uploads (CZI/LSM) need long timeouts
        timeout: 30 * 60 * 1000,
        proxyTimeout: 30 * 60 * 1000,
      }
    }
  }
});
