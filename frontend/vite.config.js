import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run mock` (mode "mock") serves the real web UI on built-in sample data: the fake backend in mock/ answers
// under /mock-api, so no API, database or Docker is needed. It's only loaded in that mode; builds never include it.
export default defineConfig(async ({ mode }) => {
  const mock = mode === "mock";
  const plugins = [react()];
  if (mock) {
    const { mockApi } = await import("./mock/server.js");
    plugins.push(mockApi());
  }
  return {
    plugins,
    server: {
      host: true,
      port: mock ? 3637 : 3636, // the mockup runs beside a real Farmhand on 3636
      strictPort: true,
    },
    preview: {
      host: true,
      port: 3636,
      strictPort: true,
    },
  };
});
