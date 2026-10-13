import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In development the browser talks to the same /api/* prefixes the nginx gateway serves in
// production; Vite proxies them to the ports published by docker-compose.dev.yml.
const service = (port: number) => ({
  target: `http://127.0.0.1:${port}`,
  changeOrigin: true,
  rewrite: (path: string) => path.replace(/^\/api\/[a-z]+/, ""),
});

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api/orchestrator": service(8000),
      "/api/evaluator": service(8002),
      "/api/knowledge": service(8003),
      "/api/memory": service(8004),
    },
  },
  build: {
    sourcemap: true,
    chunkSizeWarningLimit: 900,
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
