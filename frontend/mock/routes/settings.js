// Settings, the Storage page and network shares.
import { withNewAverage } from "../../src/lib/energyPrice.js";
import { notInMockup, nowUnix } from "../core.js";
import { iso } from "../data.js";

// where a card's picture and words are, as parts of the square (services/live_stream.py _picture_box, _text_box)
const part = (v, least, most, d) => (typeof v === "number" && Number.isFinite(v) ? Math.round(Math.min(most, Math.max(least, v)) * 1e4) / 1e4 : d);
const pictureBox = (b) => {
  if (!b || typeof b !== "object") return { x: 0, y: 0, w: 1, h: 1 };
  const w = part(b.w, 0.05, 1, 1), h = part(b.h, 0.05, 1, 1);
  return { x: part(b.x, 0, 1 - w, (1 - w) / 2), y: part(b.y, 0, 1 - h, (1 - h) / 2), w, h };
};
const textBox = (b, size, position) =>
  b && typeof b === "object"
    ? { x: part(b.x, 0, 1, 0.5), y: part(b.y, 0, 1, 0.5), size: part(b.size, 0.02, 0.6, 0.125) }
    : { x: 0.5, y: { top: 0.18, bottom: 0.82 }[position] ?? 0.5, size: Math.round(({ small: 1 / 12, large: 1 / 5 }[size] ?? 0.125) * 1e4) / 1e4 };
const cameraCell = (x) => {
  // a camera's square, and only what differs from the usual (services/live_stream.py _camera_cell)
  const out = { camera: x.camera };
  if (/^#[0-9A-Fa-f]{6}$/.test(x.background || "")) out.background = x.background.toUpperCase();
  if (x.show_words === false) out.show_words = false;
  if (typeof x.words_size === "number" && Number.isFinite(x.words_size)) out.words_size = Math.round(Math.min(0.3, Math.max(0.02, x.words_size)) * 1e4) / 1e4;
  if (/^#[0-9A-Fa-f]{6}$/.test(x.words_color || "") && x.words_color.toUpperCase() !== "#FFFFFF") out.words_color = x.words_color.toUpperCase();
  if (typeof x.words_font === "string" && x.words_font && x.words_font !== "play") out.words_font = x.words_font;
  return out;
};

export function settingsRoutes(ctx) {
  const { capability, fail404, farm, location, monthOf, on, prices, projectsDefault, requireConfirm, SCAN_ROOT, scanFolders } = ctx;

  // ------------------------------------------------------------------ settings, storage, shares
  const storageOut = () => ({ browse_root: "/data", stl: location(farm.storage.stl), threemf: location(farm.storage.threemf), project: location(farm.storage.project), outside: { stl: 0, threemf: 0, project: 0 } });
  const configLocation = () => ({
    path: farm.settingsFolder, is_set: !!farm.settingsFolder,
    status: farm.settingsFolder ? { exists: true, writable: true, marker_ok: true, ready: true } : null,
    file: farm.settingsFolder ? { exists: true, modified_at: iso(nowUnix() - 300), size: 2841 } : null,
    last_write: { ok: true, error: null, at: iso(nowUnix() - 300) },
  });
  on("GET", "/settings/config", () => ({ config: farm.config, location: configLocation() }));
  on("PUT", "/settings/config", (_, body) => {
    if (body.appearance) farm.config.appearance = { ...farm.config.appearance, ...body.appearance };
    const pricesBefore = prices(); // the average cost and its history before this save
    if (body.preferences) farm.config.preferences = { ...farm.config.preferences, ...body.preferences };
    if (body.preferences?.tool_links) {
      // as the server does: trimmed, and web addresses only
      farm.config.preferences.tool_links = (Array.isArray(body.preferences.tool_links) ? body.preferences.tool_links : [])
        .filter((l) => l && typeof l === "object")
        .map((l) => ({ name: typeof l.name === "string" ? l.name.trim() : "", url: typeof l.url === "string" ? l.url.trim() : "" }))
        .filter((l) => /^https?:\/\/[^\s/]+/i.test(l.url) && l.url.length <= 2000 && l.name.length <= 100)
        .slice(0, 200);
    }
    if (body.preferences?.stream_layouts) {
      // as the server does: named (trimmed, unique in any case, up to 60 characters), a 1x1 to 5x5 grid of squares (a
      // camera, each once; a logo; or nothing), timings in range, a #RRGGBB border
      const seen = new Set();
      const inRange = (v, least, most, fallback) => (Number.isInteger(v) && v >= least && v <= most ? v : fallback);
      const side = (v) => (Number.isInteger(v) && v >= 1 && v <= 5 ? v : null);
      const hex = (v, d) => (/^#[0-9A-Fa-f]{6}$/.test(v || "") ? v.toUpperCase() : d);
      const cellOf = (x) => {
        if (x && typeof x.camera === "string" && x.camera && x.camera.length <= 200) return cameraCell(x);
        if (x && ["background", "image", "slideshow", "text"].some((k) => k in x)) {
          const name = (v) => (typeof v === "string" && /^[^/\\]{1,120}$/.test(v) ? v : null);
          return {
            background: hex(x.background, null), image: x.slideshow ? null : name(x.image), slideshow: name(x.slideshow),
            seconds: Number.isInteger(x.seconds) && x.seconds >= 3 && x.seconds <= 3600 ? x.seconds : 10,
            text: typeof x.text === "string" ? x.text.trim().slice(0, 500) : "", color: hex(x.color, "#FFFFFF"), font: typeof x.font === "string" ? x.font : "play", band: x.band === true,
            picture_box: pictureBox(x.picture_box), text_box: textBox(x.text_box, x.size, x.position),
          };
        }
        return null;
      };
      farm.config.preferences.stream_layouts = (Array.isArray(body.preferences.stream_layouts) ? body.preferences.stream_layouts : [])
        .filter((l) => l && typeof l === "object" && typeof l.name === "string")
        .map((l) => {
          const [cols, rows] = side(l.cols) && side(l.rows) ? [l.cols, l.rows] : [1, 1];
          const cells = Array.from({ length: cols * rows }, (_, i) => cellOf((Array.isArray(l.cells) ? l.cells : [])[i]));
          const taken = new Set();
          return {
            name: l.name.trim(), cols, rows,
            cells: cells.map((x) => (x?.camera ? (taken.has(x.camera) ? null : (taken.add(x.camera), x)) : x)),
            layout: l.layout === "cycle" ? "cycle" : "grid",
            seconds_all: inRange(l.seconds_all, 0, 3600, 30),
            seconds_each: inRange(l.seconds_each, 3, 3600, 20),
            show_status: l.show_status !== false,
            border_color: /^#[0-9A-Fa-f]{6}$/.test(l.border_color || "") ? l.border_color.toUpperCase() : "#000000",
            background: /^#[0-9A-Fa-f]{6}$/.test(l.background || "") ? l.background.toUpperCase() : "#000000",
          };
        })
        .filter((l) => l.name && l.name.length <= 60 && !seen.has(l.name.toLowerCase()) && seen.add(l.name.toLowerCase()))
        .slice(0, 50);
    }
    if (body.preferences && "energy_price_per_kwh" in body.preferences) {
      // as the server does: a number from 0 to 100, else not set
      // ...and, as the server does, it counts from the month the page says it is on; earlier months keep theirs
      const v = body.preferences.energy_price_per_kwh;
      const price = typeof v === "number" && v >= 0 && v <= 100 ? Math.round(v * 100000) / 100000 : null;
      const month = /^\d{4}-\d{2}$/.test(body.preferences.energy_price_from || "") ? body.preferences.energy_price_from : monthOf(nowUnix());
      const next = withNewAverage(pricesBefore, price, month);
      Object.assign(farm.config.preferences, { energy_price_per_kwh: price, energy_price_history: next.history });
    }
    delete farm.config.preferences.energy_price_from;
    if (body.preferences && "energy_price_months" in body.preferences) {
      const months = {};
      for (const [k, v] of Object.entries(body.preferences.energy_price_months || {})) {
        if (/^\d{4}-(0[1-9]|1[0-2])$/.test(k) && typeof v === "number" && v >= 0 && v <= 100) months[k] = Math.round(v * 100000) / 100000;
      }
      farm.config.preferences.energy_price_months = months;
    }
    return { config: farm.config, mirror: { ok: true, skipped: !farm.settingsFolder, path: farm.settingsFolder, error: null } };
  });
  on("GET", "/settings/config/location/inspect", (_, _b, q) => ({ path: q.get("path"), file_exists: false, file_valid: null, modified_at: null, summary: null, error: null }));
  on("PUT", "/settings/config/location", (_, body) => {
    farm.settingsFolder = body.path || null;
    return { saved: true, needs_choice: false, found: null, restored: null, location: configLocation() };
  });
  on("POST", "/settings/config/save-now", () => ({ ok: true, skipped: false, path: farm.settingsFolder, error: null }));
  // Save all: with no folder chosen, "farmhand-configs" beside the STL folder (as the server does); every model's,
  // 3MF's and project's record is written beside its files too
  on("POST", "/settings/config/save-all", () => {
    if (!farm.settingsFolder) farm.settingsFolder = farm.storage.stl.replace(/\/[^/]*$/, "") + "/farmhand-configs";
    return {
      saved: true, needs_choice: false, found: null, restored: null, location: configLocation(),
      mirror: { ok: true, skipped: false, path: farm.settingsFolder, error: null },
      records: { library: farm.models.length + farm.bundles.length, projects: farm.projects.length },
    };
  });
  on("POST", "/settings/config/restore", () => ({ restored: ["appearance", "display preferences"], shares_added: [], shares_kept: ["farm-nas"], needs_password: [], warnings: [], records: null,
    // the mockup has no other Farmhand sharing its folders: nothing to bring in
    brought_in: { models: [], threemfs: [], projects: [] } }));

  on("GET", "/settings/storage", () => storageOut());
  on("PUT", "/settings/storage", (_, body) => {
    if ("stl_path" in body) farm.storage.stl = body.stl_path || "/data/storage/source_models";
    if ("threemf_path" in body) farm.storage.threemf = body.threemf_path || "/data/storage/bundles";
    if ("project_path" in body) farm.storage.project = body.project_path || projectsDefault();
    return storageOut();
  });
  on("GET", "/settings/storage/browse", (_, _b, q) => {
    const path = q.get("path") || "/data";
    const tree = { "/data": ["nas", "storage"], "/data/nas": ["farm-nas"], "/data/nas/farm-nas": ["3mf", "farmhand-settings", "models", "projects"], [SCAN_ROOT]: Object.keys(scanFolders), "/data/storage": ["bundles", "projects", "source_models"] };
    const parent = path === "/data" ? null : path.split("/").slice(0, -1).join("/") || "/data";
    return { path, root: "/data", parent, entries: (tree[path] || []).map((name) => ({ name, path: `${path}/${name}`, is_mount: path === "/data/nas" })) };
  });
  on("POST", "/settings/storage/folders", () => { throw notInMockup("Making folders"); });
  on("POST", "/settings/storage/migrate", () => ({ moved_stl: 0, moved_threemf: 0, moved_project: 0, missing: [], failed: [] }));
  on("GET", "/settings/storage/shares", () => ({ shares: farm.shares, capability }));
  on("POST", "/settings/storage/shares", () => { throw notInMockup("Connecting a network share"); });
  on("PATCH", "/settings/storage/shares/:id", () => { throw notInMockup("Changing a network share"); });
  on("POST", "/settings/storage/shares/:id/connect", ({ id }) => farm.shares.find((s) => s.id === Number(id)) || fail404("Share not found"));
  on("DELETE", "/settings/storage/shares/:id", ({ id }, _b, q) => {
    requireConfirm(q, "Pass confirm=true to proceed");
    farm.shares = farm.shares.filter((s) => s.id !== Number(id));
    return [204, null];
  });
  return { storageOut, configLocation };
}
