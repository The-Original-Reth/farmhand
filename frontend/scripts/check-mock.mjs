// npm run check:mock: does the mock backend (mock/) answer every route the real API has, and nothing it doesn't?
// The real routes are mock/api-routes.json, written by `python -m app.api_routes` in backend/ (the backend's tests fail
// while it's out of date). Each real route is tried against the mock's routes with a made-up value in each {part};
// each mock route the other way round. Exits 1 when they differ in a way not listed below, with why, as known.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { createCore } from "../mock/core.js";
import { projectsRoutes } from "../mock/routes/projects.js";
import { printersRoutes } from "../mock/routes/printers.js";
import { libraryRoutes } from "../mock/routes/library.js";
import { printingRoutes } from "../mock/routes/printing.js";
import { settingsRoutes } from "../mock/routes/settings.js";
import { filesRoutes } from "../mock/routes/files.js";
import { pluginsRoutes } from "../mock/routes/plugins.js";
import { backupsRoutes } from "../mock/routes/backups.js";
import { streamControlRoutes } from "../mock/routes/streamControl.js";

// Real routes the mock leaves out on purpose (the page never calls them, or needs a real file or a plugin)
const NOT_IN_MOCK = {
  "GET /health": "the container's health check",
  "GET /source-models/{source_model_id}/bundles": "not called by the page",
  "GET /stream-control/fonts/{key}": "a real font file: the page falls back to its kind of font",
  "GET /stream-control/music/{name}": "a real track: the page's player stays quiet",
  "GET /plugin-api/v1/prints/{ticket}/file": "a plugin fetching a G-code: no real plugin runs against the mock",
  "GET /plugin-api/v1/stream/pictures/{name}": "a plugin fetching a picture: no real plugin runs against the mock",
  "GET /plugin-api/v1/stream/slideshows/{show}/pictures/{name}": "a plugin fetching a picture: no real plugin runs against the mock",
  "GET /plugin-api/v1/stream/music/{name}": "a plugin fetching a track: no real plugin runs against the mock",
  "GET /plugin-api/v1/backup": "a plugin fetching its settings copy: no real plugin runs against the mock",
  "PUT /plugin-api/v1/backup": "a plugin saving its settings copy: no real plugin runs against the mock",
};
// Mock routes with no real one: stand-ins for things outside Farmhand
const MOCK_ONLY = {
  "GET /printers/:id/webcam/state": "a printer's camera (ustreamer) answering, as the printer itself would",
};

const ctx = createCore();
for (const add of [projectsRoutes, printersRoutes, libraryRoutes, printingRoutes, settingsRoutes, filesRoutes, pluginsRoutes, streamControlRoutes, backupsRoutes]) Object.assign(ctx, add(ctx));
const { routes, fileRoutes, downloadRoutes } = ctx;
// the project file view server.js answers itself
const VIEW = /^\/projects\/(\d+)\/(doc|cad|stl|threemf)\/(\d+)\/versions\/(\d+)\/view$/;

const PART = /\{[^}]+\}/g; // a real route's {part}
const sample = (path) => path.replace(PART, "1");
const realRe = (path) => new RegExp("^" + path.replace(PART, "[^/]+") + "$");
const mockAnswers = (method, path) =>
  routes.some((r) => r.method === method && r.re.test(path)) ||
  (method === "GET" && [...fileRoutes, ...downloadRoutes].some(([re]) => re.test(path))) ||
  (method === "GET" && VIEW.test(path));

const real = JSON.parse(readFileSync(fileURLToPath(new URL("../mock/api-routes.json", import.meta.url)), "utf-8"));
const missing = real.filter(([m, p]) => !mockAnswers(m, sample(p)) && !(`${m} ${p}` in NOT_IN_MOCK)).map(([m, p]) => `${m} ${p}`);
const nowServed = Object.keys(NOT_IN_MOCK).filter((k) => {
  const [m, p] = k.split(" ");
  return mockAnswers(m, sample(p)) || !real.some(([rm, rp]) => rm === m && rp === p);
});

// a mock route is real when some real route of its method, with made-up values, is one it answers, or the other way
// round (the real PATCH /plugins/{plugin_id} is the mock's PATCH /plugins/stream-control)
const isReal = (r) => real.some(([m, p]) => m === r.method && (r.re.test(sample(p)) || realRe(p).test(r.pattern.replace(/:\w+/g, "1"))));
const extra = routes.filter((r) => !isReal(r)).map((r) => `${r.method} ${r.pattern}`).filter((k) => !(k in MOCK_ONLY));

let ok = true;
if (missing.length) {
  ok = false;
  console.log(`Real routes the mock doesn't answer (mirror them in mock/routes/, or list them in NOT_IN_MOCK with why):\n  ${missing.join("\n  ")}`);
}
if (extra.length) {
  ok = false;
  console.log(`Mock routes the real API doesn't have (removed or renamed there? Or list them in MOCK_ONLY with why):\n  ${extra.join("\n  ")}`);
}
if (nowServed.length) {
  ok = false;
  console.log(`Listed in NOT_IN_MOCK but now answered by the mock, or gone from the API (take them off the list):\n  ${nowServed.join("\n  ")}`);
}
const skipped = Object.keys(NOT_IN_MOCK).length;
if (ok) console.log(`The mock answers all ${real.length - skipped} real routes it should (${skipped} left out on purpose), and no others.`);
process.exit(ok ? 0 : 1);
