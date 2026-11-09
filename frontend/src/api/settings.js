// Settings: appearance and preferences, kept on the server, and their copy on the NAS (Save all / Load all).
import { API_BASE, jsonBody, post, request } from "./client.js";

const normalizeConfigLocation = (l) => ({
  path: l.path,
  isSet: l.is_set,
  status: l.status && { exists: l.status.exists, writable: l.status.writable, markerOk: l.status.marker_ok, ready: l.status.ready },
  file: l.file && { exists: l.file.exists, modifiedAt: l.file.modified_at, size: l.file.size },
  lastWrite: { ok: l.last_write.ok, error: l.last_write.error, at: l.last_write.at },
});

const normalizeRestore = (r) =>
  r && {
    restored: r.restored,
    sharesAdded: r.shares_added,
    sharesKept: r.shares_kept,
    needsPassword: r.needs_password,
    warnings: r.warnings,
    // from the printers/ and models/ files
    records: r.records && {
      printersAdded: r.records.printers_added || [],
      printersFilled: r.records.printers_filled || [],
      printsAdded: r.records.prints_added || 0,
      readingsAdded: r.records.readings_added || 0,
      modelNotes: r.records.model_notes || 0,
      threemfNotes: r.records.threemf_notes || 0,
      stars: r.records.stars || 0,
      modelsMissing: r.records.models_missing || [],
    },
  };

export const normalizeFound = (f) =>
  f && {
    path: f.path,
    fileExists: f.file_exists,
    fileValid: f.file_valid,
    modifiedAt: f.modified_at,
    error: f.error,
    summary: f.summary && {
      savedAt: f.summary.saved_at,
      scheme: f.summary.scheme,
      shares: f.summary.shares,
      hasStlFolder: f.summary.has_stl_folder,
      hasThreemfFolder: f.summary.has_threemf_folder,
      hasProjectFolder: !!f.summary.has_project_folder,
      printers: f.summary.printers || 0, // printer files in its printers/ folder
      models: f.summary.models || 0,
    },
  };

export const getConfig = async () => {
  const r = await request("/settings/config");
  return { config: r.config, location: normalizeConfigLocation(r.location) };
};

// Send only the parts that changed: { appearance } and/or { preferences: { model_sort } }
export const saveConfig = (patch) => request("/settings/config", jsonBody("PUT", patch));

export const inspectConfigFolder = async (path) =>
  normalizeFound(await request(`/settings/config/location/inspect?path=${encodeURIComponent(path)}`));

// ifExists: "ask" (the default: a folder that already holds settings is NOT touched), "restore" or "overwrite"
export const setConfigLocation = async ({ path, ifExists = "ask" }) => {
  const r = await request("/settings/config/location", jsonBody("PUT", { path, if_exists: ifExists }));
  return {
    saved: r.saved,
    needsChoice: r.needs_choice,
    found: normalizeFound(r.found),
    restored: normalizeRestore(r.restored),
    location: normalizeConfigLocation(r.location),
  };
};

// For the moment a page is closing: `keepalive` lets the request finish after the page has gone
export const saveConfigOnExit = (patch) => {
  try {
    fetch(`${API_BASE}/settings/config`, { ...jsonBody("PUT", patch), keepalive: true });
  } catch {
    /* nothing more can be done; the unsent change is remembered and tried again on the next visit */
  }
};

// Save all: every setting, printer and model written to the settings folder now, and every model's, 3MF's and
// project's record beside its files (records: how many projects', and models' and 3MFs', were written). With no folder chosen, Farmhand picks
// "farmhand-configs" beside the STL folder; one already holding settings needs a choice first (needsChoice, found),
// answered with setConfigLocation({ path: found.path, ifExists }).
export const saveAllSettings = async (ifExists = "ask") => {
  const r = await request("/settings/config/save-all", jsonBody("POST", { if_exists: ifExists }));
  return {
    saved: r.saved,
    needsChoice: r.needs_choice,
    found: normalizeFound(r.found),
    restored: normalizeRestore(r.restored),
    location: normalizeConfigLocation(r.location),
    mirror: r.mirror,
    records: r.records || null,
  };
};

export const restoreConfig = async () => normalizeRestore(await post("/settings/config/restore"));

// ---- scanning the STL folder for files added from outside Farmhand ----
