// Settings, the Storage page and network shares.
import { withNewAverage } from "../../src/lib/energyPrice.js";
import { notInMockup, nowUnix } from "../core.js";
import { iso } from "../data.js";

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
  // Save all: with no folder chosen, "farmhand-configs" beside the STL folder (as the server does)
  on("POST", "/settings/config/save-all", () => {
    if (!farm.settingsFolder) farm.settingsFolder = farm.storage.stl.replace(/\/[^/]*$/, "") + "/farmhand-configs";
    return {
      saved: true, needs_choice: false, found: null, restored: null, location: configLocation(),
      mirror: { ok: true, skipped: false, path: farm.settingsFolder, error: null },
    };
  });
  on("POST", "/settings/config/restore", () => ({ restored: ["appearance", "display preferences"], shares_added: [], shares_kept: ["farm-nas"], needs_password: [], warnings: [], records: null }));

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
