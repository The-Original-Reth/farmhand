import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The Stream plugin's page. Built into ../streamer/web, which the plugin serves at its own "/" (and Farmhand shows at
// /plugins/stream/). base "./": every address in it is relative, so it works both inside Farmhand and opened straight
// on the plugin. `npm run dev` passes /api on to a plugin running at STREAM_PLUGIN (default http://localhost:8080).
export default defineConfig({
  base: "./",
  plugins: [react()],
  build: { outDir: "../streamer/web", emptyOutDir: true },
  server: { port: 3638, proxy: { "/api": process.env.STREAM_PLUGIN || "http://localhost:8080" } },
});
