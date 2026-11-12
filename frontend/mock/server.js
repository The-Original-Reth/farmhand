// The mockup's backend: a Vite plugin that answers the web UI's API calls under /mock-api from the sample farm in
// data.js, in exactly the shapes the real FastAPI backend uses. Changes (notes, stars, maintenance...) are kept in
// memory until the mockup restarts. Things that need real files or hardware (STL uploads, scanning, NAS mounting)
// answer with a plain "not in the mockup" message; a 3MF upload is read from its file name (see readThreemf). Only loaded by `npm run mock` (see vite.config.js).
//
// mock/core.js holds the farm and the helpers every part shares; each part's routes are in mock/routes/.
import { createCore, HttpError, PREFIX } from "./core.js";
import { projectsRoutes } from "./routes/projects.js";
import { printersRoutes } from "./routes/printers.js";
import { libraryRoutes } from "./routes/library.js";
import { printingRoutes } from "./routes/printing.js";
import { settingsRoutes } from "./routes/settings.js";
import { filesRoutes } from "./routes/files.js";
import { pluginsRoutes } from "./routes/plugins.js";

export function mockApi() {
  const ctx = createCore();
  for (const add of [projectsRoutes, printersRoutes, libraryRoutes, printingRoutes, settingsRoutes, filesRoutes, pluginsRoutes]) Object.assign(ctx, add(ctx));
  const { routes, resetFarm, fileRoutes, downloadRoutes, fileVersion, pluginPageRequest } = ctx;

  // ------------------------------------------------------------------ the Vite plugin
  return {
    name: "farmhand-mock-api",
    configureServer(server) {
      // a plugin's page, as nginx passes /plugins/<id>/ on in the real Farmhand (the bare /plugins is the Plugins page)
      server.middlewares.use((req, res, next) => {
        if (!/^\/plugins\/[^/]/.test(req.url) || !pluginPageRequest(req, res)) next();
      });
      server.middlewares.use(PREFIX, async (req, res) => {
        const url = new URL(req.url, "http://mock");
        const send = (status, body, type = "application/json") => {
          res.statusCode = status;
          res.setHeader("Cache-Control", "no-store");
          if (body == null) return res.end();
          res.setHeader("Content-Type", type);
          res.end(type === "application/json" ? JSON.stringify(body) : body);
        };
        try {
          if (req.method === "POST" && url.pathname === "/__reset") {
            resetFarm();
            return send(200, { reset: true });
          }
          if (req.method === "GET") {
            for (const [re, get] of fileRoutes) {
              const m = url.pathname.match(re);
              if (m) {
                const image = get(m);
                if (image?.type) return send(200, image.body, image.type); // not a picture: { body, type }
                return image ? send(200, image, "image/png") : send(404, { detail: "No thumbnail for this version" });
              }
            }
            for (const [re, get] of downloadRoutes) {
              const m = url.pathname.match(re);
              if (m) {
                const [name] = get(m);
                res.setHeader("Content-Disposition", `attachment; filename="${name}"`);
                return send(200, `Farmhand mockup: a stand-in for ${name}. The real file comes from the real backend.\n`, "text/plain");
              }
            }
            // a project file opened in the browser: shown (as the real one is), here as a stand-in
            const view = url.pathname.match(/^\/projects\/(\d+)\/(doc|cad|stl|threemf)\/(\d+)\/versions\/(\d+)\/view$/);
            if (view) {
              const name = fileVersion(view[1], view[2], view[3], view[4]).filename;
              res.setHeader("Content-Disposition", `inline; filename="${name}"`);
              return send(200, `Farmhand mockup: ${name} would open here. The real file comes from the real backend.\n`, "text/plain");
            }
          }
          const chunks = [];
          for await (const chunk of req) chunks.push(chunk);
          const raw = Buffer.concat(chunks).toString("utf-8");
          let body = {};
          if (raw && (req.headers["content-type"] || "").includes("application/json")) body = JSON.parse(raw);
          // an upload: only the names of the files sent, and its text fields, are kept (the mockup doesn't store files)
          if ((req.headers["content-type"] || "").includes("multipart/form-data")) {
            body = {
              files: [...raw.matchAll(/filename="([^"]*)"/g)].map((m) => m[1]),
              fields: Object.fromEntries([...raw.matchAll(/name="([^"]+)"\r\n\r\n([^\r]*)\r\n/g)].map((m) => [m[1], m[2]])),
            };
          }
          for (const r of routes) {
            if (r.method !== req.method) continue;
            const m = url.pathname.match(r.re);
            if (!m) continue;
            const params = Object.fromEntries(r.keys.map((k, i) => [k, m[i + 1]]));
            await new Promise((done) => setTimeout(done, 120 + Math.random() * 180)); // feels like a real network
            const out = await r.handler(params, body, url.searchParams, req.headers);
            if (typeof out?.stream === "function") return out.stream(req, res); // server-sent events (the plugin API's /events)
            return Array.isArray(out) && typeof out[0] === "number" && out.length === 2 ? send(out[0], out[1]) : send(200, out);
          }
          return send(404, { detail: `The mockup doesn't know ${req.method} ${url.pathname}` });
        } catch (e) {
          if (e instanceof HttpError) return send(e.status, { detail: e.message, ...e.extra });
          console.error("[mock-api]", e);
          return send(500, { detail: `Mockup error: ${e.message}` });
        }
      });
      server.config.logger.info("  Farmhand mockup: sample data served at /mock-api (no backend needed)");
    },
  };
}
