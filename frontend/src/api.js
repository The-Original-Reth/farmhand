// Default to whatever host the browser is actually using, not a hardcoded
// "localhost" — that breaks the moment this is viewed from a different
// machine than the one running Docker (e.g. a phone/laptop hitting a
// Raspberry Pi's LAN IP). VITE_API_BASE still overrides this when set.
const defaultApiBase = `${window.location.protocol}//${window.location.hostname}:5546`;
export const API_BASE = import.meta.env.VITE_API_BASE || defaultApiBase;

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    let body = null;
    try {
      body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    const error = new Error(detail);
    error.status = res.status;
    error.body = body;
    throw error;
  }
  return res.status === 204 ? null : res.json();
}

const fmtDate = (iso) =>
  iso ? new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "—";

// ---- normalizers: API shape -> the shape the UI components use ----

export const normalizePrinter = (p) => ({
  id: p.id,
  name: p.name,
  kind: p.kind || "",
  wired: p.wired_ip,
  wireless: p.wireless_ip,
  decommissioned: p.decommissioned,
  notes: p.notes || "", // free text about the printer
  notesRevision: p.notes_revision || 0, // names one exact version of the text: a save is refused if it has moved on
  notesUpdatedAt: p.notes_updated_at || null,
});

// After previews are redrawn their URLs don't change, so the browser would keep showing the old image.
// Bumping this adds a fresh ?b= to every STL preview URL the next time models are loaded.
let thumbnailBust = 0;
export const bustThumbnails = () => {
  thumbnailBust = Date.now();
};
const withBust = (url) => (thumbnailBust ? `${url}?b=${thumbnailBust}` : url);

export const normalizeSourceModel = (m) => {
  const versions = (m.versions || []).map((v) => ({
    id: v.id,
    v: v.version,
    date: fmtDate(v.uploaded_at),
    note: v.note,
    thumb: v.thumbnail_path ? withBust(`${API_BASE}/source-models/${m.id}/versions/${v.version}/thumbnail`) : null,
    sourceModelId: m.id,
  })).sort((x, y) => y.v - x.v); // newest on top
  return {
    id: m.id,
    name: m.name,
    type: m.file_type,
    created: m.created_at, // when the model was added (for sorting)
    added: fmtDate(m.created_at),
    thumb: versions.find((v) => v.thumb)?.thumb || null,
    versions,
    notes: m.notes || "", // free text about the whole model
    notesRevision: m.notes_revision || 0, // names one exact version of the text: a save is refused if it has moved on
    notesUpdatedAt: m.notes_updated_at || null,
  };
};

export const normalizeBundle = (b) => {
  const versions = (b.versions || []).map((v) => ({
    id: v.id,
    v: v.version,
    date: fmtDate(v.uploaded_at),
    monument: v.monument,
    note: v.monument_note,
    full: v.full_files_retained,
    filename: v.filename,
    slicer: v.slicer_display_name,
    uploaded: v.uploaded_at,
    thumb: v.thumbnail_path ? `${API_BASE}/bundles/versions/${v.id}/thumbnail` : null,
  })).sort((x, y) => y.v - x.v); // newest on top, whatever order the server used
  const latest = versions[0];
  return {
    id: b.id,
    name: latest?.filename || `bundle-${b.id}`,
    updated: latest?.uploaded, // when its newest version was added: how entries are ordered under a printer
    slicer: latest?.slicer || "",
    printerId: b.printer_id,
    sourceModelIds: (b.source_models || []).map((m) => m.id),
    versions,
    starredVersionId: b.starred_version_id ?? null, // the one version starred gold, if any (never v1)
    notes: b.notes || "", // free text about this 3MF, shared by all its versions
    notesRevision: b.notes_revision || 0, // names one exact version of the text: a save is refused if it has moved on
    notesUpdatedAt: b.notes_updated_at || null,
  };
};

// ---- reads ----

export const fetchAll = async () => {
  const [printers, models, bundles] = await Promise.all([
    request("/printers"),
    request("/source-models"),
    request("/bundles"),
  ]);
  return {
    printers: printers.map(normalizePrinter),
    sourceModels: models.map(normalizeSourceModel),
    bundles: bundles.map(normalizeBundle),
  };
};

export const fetchVersionSettings = async (versionId) => {
  const detail = await request(`/bundles/versions/${versionId}`);
  return detail.settings || {};
};

// ---- writes ----

const ext = (name) => (name.split(".").pop() || "").toLowerCase();
const typeFromExt = (e) => {
  if (e === "stl") return "STL";
  if (e === "obj") return "OBJ";
  if (e === "step" || e === "stp") return "STEP";
  return null;
};

// The folder "name" is just a display label the user typed — it's not
// guaranteed to end in a real file extension. The actual uploaded FILE's
// own name is the authoritative source for file type; only fall back to
// guessing from the label when no file was attached yet (creating an
// empty folder to fill in later), and default to STL rather than
// blocking folder creation over a field that's provisional anyway.
export const fileTypeFor = ({ name, file }) => {
  if (file) {
    const t = typeFromExt(ext(file.name));
    if (t) return t;
    throw new Error(`Unsupported file type ".${ext(file.name)}" — expected STL, OBJ, or STEP`);
  }
  return typeFromExt(ext(name)) || "STL";
};

export const createPrinter = ({ name, kind, wiredIp, wirelessIp }) =>
  request("/printers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name,
      kind: kind || null,
      wired_ip: wiredIp || null,
      wireless_ip: wirelessIp || null,
    }),
  });

export const createSourceModel = ({ name, file }) => {
  const form = new FormData();
  form.append("name", name);
  form.append("file_type", fileTypeFor({ name, file }));
  if (file) form.append("file", file);
  return request("/source-models", { method: "POST", body: form });
};

export const createBundle = ({ sourceModelIds, threemf, gcode, printerId }) => {
  const form = new FormData();
  form.append("source_model_ids", JSON.stringify(sourceModelIds));
  form.append("threemf", threemf);
  if (gcode) form.append("gcode", gcode); // optional
  // When omitted, the backend reads the printer from the 3MF's own profile.
  if (printerId != null) form.append("printer_id", String(printerId));
  return request("/bundles", { method: "POST", body: form });
};

// Ask the backend what a 3MF says about itself (which printer it was sliced
// for, and whether that printer is registered) without storing anything.
export const inspectThreemf = async (threemf) => {
  const form = new FormData();
  form.append("threemf", threemf);
  const r = await request("/bundles/inspect", { method: "POST", body: form });
  return {
    printerProfileName: r.printer_profile_name,
    slicer: r.slicer_display_name,
    matchedPrinter: r.matched_printer ? normalizePrinter(r.matched_printer) : null,
  };
};

export const addBundleVersion = ({ bundleId, threemf, gcode }) => {
  const form = new FormData();
  form.append("threemf", threemf);
  if (gcode) form.append("gcode", gcode); // optional
  return request(`/bundles/${bundleId}/versions`, { method: "POST", body: form });
};

export const updatePrinter = (id, { name, kind, wiredIp, wirelessIp, decommissioned }) =>
  request(`/printers/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    // Blank optional fields are sent as null so they actually clear
    body: JSON.stringify({
      name,
      kind: kind || null,
      wired_ip: wiredIp || null,
      wireless_ip: wirelessIp || null,
      decommissioned: !!decommissioned,
    }),
  });

export const addSourceModelVersion = ({ modelId, file, note }) => {
  const form = new FormData();
  form.append("file", file);
  if (note) form.append("note", note);
  return request(`/source-models/${modelId}/versions`, { method: "POST", body: form });
};

// ---- notes about a model ----
// baseRevision is the revision the text was written from (0 = there were none). If someone else has saved since, the
// server answers 409 and the error's .body.current holds their version: nothing is overwritten.
export const saveModelNotes = ({ modelId, notes, baseRevision }) =>
  request(`/source-models/${modelId}/notes`, jsonBody("PUT", { notes, base_revision: baseRevision }));

// ---- notes about a printer (the same rules as a model's: a save names the revision it started from) ----
export const savePrinterNotes = ({ printerId, notes, baseRevision }) =>
  request(`/printers/${printerId}/notes`, jsonBody("PUT", { notes, base_revision: baseRevision }));

// ---- notes about a 3MF (the same rules again) ----
export const saveBundleNotes = ({ bundleId, notes, baseRevision }) =>
  request(`/bundles/${bundleId}/notes`, jsonBody("PUT", { notes, base_revision: baseRevision }));

// Star one version of a 3MF (only one per 3MF; never v1), or pass versionId: null to clear the star
export const setStarredVersion = ({ bundleId, versionId }) =>
  request(`/bundles/${bundleId}/star`, jsonBody("PUT", { version_id: versionId }));

// ---- deletes ----
// The API refuses deletes without confirm=true; the UI's own confirmation
// dialog is the real guard, so every call here is made after the user said yes.
const del = (path) => request(`${path}${path.includes("?") ? "&" : "?"}confirm=true`, { method: "DELETE" });

export const deleteBundleVersion = (versionId) => del(`/bundles/versions/${versionId}`);
export const deleteBundle = (bundleId) => del(`/bundles/${bundleId}`);
export const deleteSourceModelVersion = (modelId, version) =>
  del(`/source-models/${modelId}/versions/${version}`);
export const deleteSourceModel = (modelId, { cascade = false } = {}) =>
  del(`/source-models/${modelId}?cascade=${cascade ? "true" : "false"}`);

// ---- storage locations (Storage page) ----

const normalizeLocation = (l) => ({
  path: l.path,
  defaultPath: l.default_path,
  isDefault: l.is_default,
  status: {
    exists: l.status.exists,
    writable: l.status.writable,
    markerOk: l.status.marker_ok,
    ready: l.status.ready,
    freeBytes: l.status.free_bytes,
    totalBytes: l.status.total_bytes,
    separateVolume: l.status.separate_volume,
  },
});

const normalizeStorage = (r) => ({
  browseRoot: r.browse_root,
  stl: normalizeLocation(r.stl),
  threemf: normalizeLocation(r.threemf),
  outside: r.outside, // { stl, threemf }: versions whose files are still outside the selected locations
});

export const getStorageSettings = async () => normalizeStorage(await request("/settings/storage"));

// Only the locations passed are changed; null resets that one to its default.
export const saveStorageSettings = async ({ stlPath, threemfPath }) => {
  const body = {};
  if (stlPath !== undefined) body.stl_path = stlPath;
  if (threemfPath !== undefined) body.threemf_path = threemfPath;
  return normalizeStorage(
    await request("/settings/storage", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
};

const normalizeBrowse = (r) => ({
  path: r.path,
  root: r.root,
  parent: r.parent,
  entries: r.entries.map((e) => ({ name: e.name, path: e.path, isMount: e.is_mount })),
});

export const browseStorage = async (path) =>
  normalizeBrowse(await request(`/settings/storage/browse${path ? `?path=${encodeURIComponent(path)}` : ""}`));

// Make a folder inside `parent` (the picker's "New folder"); resolves to that new folder's listing.
export const createFolder = async ({ parent, name }) =>
  normalizeBrowse(
    await request("/settings/storage/folders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ parent, name }),
    })
  );

// ---- network shares: connect a NAS from the web interface ----

const normalizeShare = (s) => ({
  id: s.id,
  name: s.name,
  protocol: s.protocol,
  server: s.server,
  share: s.share,
  username: s.username,
  domain: s.domain,
  version: s.version,
  hasPassword: s.has_password,
  address: s.address,
  mountPoint: s.mount_point,
  mounted: s.mounted,
  error: s.error,
  errorKind: s.error_kind,
  filesHere: s.files_here,
});

export const getShares = async () => {
  const r = await request("/settings/storage/shares");
  return { shares: r.shares.map(normalizeShare), capability: r.capability };
};

const jsonBody = (method, data) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(data),
});

// Mounts the share first and only saves it if that worked, so errors here are the real reason.
export const createShare = async (data) => normalizeShare(await request("/settings/storage/shares", jsonBody("POST", data)));
export const updateShare = async (id, data) =>
  normalizeShare(await request(`/settings/storage/shares/${id}`, jsonBody("PATCH", data)));
export const reconnectShare = async (id) =>
  normalizeShare(await request(`/settings/storage/shares/${id}/connect`, { method: "POST" }));
export const deleteShare = (id) => del(`/settings/storage/shares/${id}`);

export const migrateStorage = async () => {
  const r = await request("/settings/storage/migrate", { method: "POST" });
  return { movedStl: r.moved_stl, movedThreemf: r.moved_threemf, missing: r.missing, failed: r.failed };
};

// Redraw one version's preview from its file with the current renderer. Resolves to { updated }.
export const redrawPreview = ({ modelId, version }) =>
  request(`/source-models/${modelId}/versions/${version}/thumbnail`, { method: "POST" });

// ---- settings: appearance + display preferences, kept on the server and copied to a network folder ----

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
  };

const normalizeFound = (f) =>
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

export const saveConfigNow = () => request("/settings/config/save-now", { method: "POST" });
export const restoreConfig = async () => normalizeRestore(await request("/settings/config/restore", { method: "POST" }));

// ---- scanning the STL folder for files added from outside Farmhand ----

// Read-only: lists model files in the STL folder that aren't in the library yet.
export const scanStlFolder = async () => {
  const r = await request("/source-models/scan", { method: "POST" });
  return {
    root: r.root,
    truncated: r.truncated,
    files: r.files.map((f) => ({
      path: f.path,
      name: f.name,
      folder: f.folder,
      sizeBytes: f.size_bytes,
      fileType: f.file_type,
      nameInLibrary: f.name_in_library,
    })),
  };
};

// Adds the given files (small batches) to the library, moving each into Farmhand's own folders. Each succeeds or fails on its own.
export const importScannedFiles = async (paths) => {
  const r = await request("/source-models/scan/import", jsonBody("POST", { paths }));
  return {
    results: r.results.map((x) => ({ path: x.path, ok: x.ok, error: x.error, sourceModelId: x.source_model_id })),
  };
};

export const setMonument = ({ versionId, monument, note, confirm }) =>
  request(`/bundles/versions/${versionId}/monument`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ monument, note: note || null, confirm: !!confirm }),
  });

// ---- download URLs (plain links; the browser handles the download) ----

export const bundle3mfUrl = (versionId) => `${API_BASE}/bundles/versions/${versionId}/download/3mf`;
export const bundleGcodeUrl = (versionId) => `${API_BASE}/bundles/versions/${versionId}/download/gcode`;
export const sourceModelDownloadUrl = (modelId, version) =>
  `${API_BASE}/source-models/${modelId}/versions/${version}/download`;
