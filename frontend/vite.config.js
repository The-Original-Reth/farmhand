import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// `npm run mock` (mode "mock") serves the real web UI on built-in sample data: the fake backend in mock/ answers
// under /mock-api, so no API, database or Docker is needed. It's only loaded in that mode; builds never include it.
// The path is built at run time on purpose: Vite bundles this file before running it and would otherwise go looking
// for mock/ on every build, which fails in the Docker image (mock/ is left out by .dockerignore).
const MOCK_SERVER = new URL("./mock/server.js", import.meta.url).href;

export default defineConfig(async ({ mode }) => {
  const mock = mode === "mock";
  const apiBase = loadEnv(mode, process.cwd(), "").VITE_API_BASE || process.env.VITE_API_BASE;
  const plugins = [react()];
  if (mock) {
    const { mockApi } = await import(MOCK_SERVER);
    plugins.push(mockApi());
  }
  return {
    plugins,
    server: {
      host: true,
      port: mock ? 3637 : 3636, // the mockup runs beside a real Farmhand on 3636
      strictPort: true,
      // `npm run dev` against an API: a plugin's page at /plugins/<id>/ comes from the API's /plugins/<id>/page/, as
      // nginx.conf does it (the mockup answers them itself)
      proxy: !mock && apiBase ? {
        "^/plugins/.+": {
          target: apiBase,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/plugins\/([a-z0-9-]+)\//, "/plugins/$1/page/"),
        },
      } : undefined,
    },
    preview: {
      host: true,
      port: 3636,
      strictPort: true,
    },
  };
});
