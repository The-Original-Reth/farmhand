// Models and 3MFs: adding them and their versions, G-code, renaming, notes, stars, deleting, scanning the STL folder,
// and download links.
import { API_BASE, del, fmtDate, formBody, jsonBody, notesBody, post, request } from "./client.js";
import { normalizePrinter } from "./printers.js";

export const normalizeSourceModel = (m) => {
  const versions = (m.versions || []).map((v) => ({
    id: v.id,
    v: v.version,
    date: fmtDate(v.uploaded_at),
    note: v.note,
    thumb: v.thumbnail_path ? `${API_BASE}/source-models/${m.id}/versions/${v.version}/thumbnail?r=${v.thumbnail_rev ?? 0}` : null,
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
    slicerFamily: v.slicer_family || "prusaslicer", // which slicer wrote it: prusaslicer | orcaslicer | bambustudio
    profile: v.printer_profile_name || null, // the slicer's printer profile it was sliced under
    uploaded: v.uploaded_at,
    thumb: v.thumbnail_path ? `${API_BASE}/bundles/versions/${v.id}/thumbnail?r=${Date.parse(v.uploaded_at) || 0}` : null,
    gcodeName: v.gcode_name || null, // its G-code ("Goldfish ver 2.gcode"), if it has one
    subPrinterId: v.sub_printer_id ?? null, // the printer profile (printer preset) it was sliced with, if it names one
    subPrinter: v.sub_printer_name || null,
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

const getBundle = (bundleId) => request(`/bundles/${bundleId}`);

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
const fileTypeFor = ({ name, file }) => {
  if (file) {
    const t = typeFromExt(ext(file.name));
    if (t) return t;
    throw new Error(`Unsupported file type ".${ext(file.name)}" — expected STL, OBJ, or STEP`);
  }
  return typeFromExt(ext(name)) || "STL";
};

export const createSourceModel = ({ name, file }) =>
  request("/source-models", formBody("POST", { name, file_type: fileTypeFor({ name, file }), file: file || undefined }));

// Which printer profile a new 3MF version goes to: { subPrinterId } (one of the printer's) or { newSubPrinterName } (a new
// one); neither = the one its printer preset goes to.
const subPrinterFormFields = ({ subPrinterId, newSubPrinterName }) => ({
  sub_printer_id: subPrinterId != null ? String(subPrinterId) : undefined,
  new_sub_printer_name: newSubPrinterName || undefined,
});

export const createBundle = ({ sourceModelIds, threemf, gcode, printerId, subPrinter = {} }) =>
  request("/bundles", formBody("POST", {
    source_model_ids: JSON.stringify(sourceModelIds),
    threemf,
    gcode: gcode || undefined, // optional
    // When omitted, the backend reads the printer from the 3MF's own profile.
    printer_id: printerId != null ? String(printerId) : undefined,
    ...subPrinterFormFields(subPrinter),
  }));

// Ask the backend what a 3MF says about itself (which printer it was sliced
// for, and whether that printer is registered) without storing anything.
export const inspectThreemf = async (threemf) => {
  const r = await request("/bundles/inspect", formBody("POST", { threemf }));
  return {
    printerProfileName: r.printer_profile_name,
    printerPresetName: r.printer_preset_name || null, // the printer preset (printer profile) it was sliced with
    slicer: r.slicer_display_name,
    matchedPrinter: r.matched_printer ? normalizePrinter(r.matched_printer) : null,
  };
};

// A 3MF version's G-code (.gcode / .bgcode sliced from it), replacing one it had. Resolves to the whole 3MF.
export const uploadGcode = (versionId, gcode) => request(`/bundles/versions/${versionId}/gcode`, formBody("PUT", { gcode }));

// Sends a version's G-code to its 3MF's printer and starts it: { sent, printer }. 409 while the printer is busy.
export const sendGcode = (versionId) => post(`/bundles/versions/${versionId}/print`);

export const addBundleVersion = ({ bundleId, threemf, gcode, subPrinter = {} }) =>
  request(`/bundles/${bundleId}/versions`, formBody("POST", { threemf, gcode: gcode || undefined, ...subPrinterFormFields(subPrinter) })); // the G-code is optional

export const addSourceModelVersion = ({ modelId, file, note }) =>
  request(`/source-models/${modelId}/versions`, formBody("POST", { file, note: note || undefined }));

// ---- renaming: what a file is shown, searched and downloaded as (the stored file keeps its own name) ----
export const renameModel = (modelId, name) => request(`/source-models/${modelId}`, jsonBody("PATCH", { name }));

// ".3mf" is added if left off
const renameBundleVersion = (versionId, filename) =>
  request(`/bundles/versions/${versionId}`, jsonBody("PATCH", { filename }));

// A 3MF's name is its newest version's: rename that, and resolve to the 3MF as it now stands
export const renameBundle = async (bundle, filename) => {
  await renameBundleVersion(bundle.versions[0].id, filename);
  return getBundle(bundle.id);
};

// ---- notes about a model ----
// baseRevision is the revision the text was written from (0 = there were none). If someone else has saved since, the
// server answers 409 and the error's .body.current holds their version: nothing is overwritten.
export const saveModelNotes = ({ modelId, notes, baseRevision }) =>
  request(`/source-models/${modelId}/notes`, notesBody(notes, baseRevision));

// ---- notes about a 3MF (the same rules again) ----
export const saveBundleNotes = ({ bundleId, notes, baseRevision }) =>
  request(`/bundles/${bundleId}/notes`, notesBody(notes, baseRevision));

// Star one version of a 3MF (only one per 3MF; never v1), or pass versionId: null to clear the star
export const setStarredVersion = ({ bundleId, versionId }) =>
  request(`/bundles/${bundleId}/star`, jsonBody("PUT", { version_id: versionId }));

// ---- deletes ----

export const deleteBundleVersion = (versionId) => del(`/bundles/versions/${versionId}`);

export const deleteBundle = (bundleId) => del(`/bundles/${bundleId}`);

export const deleteSourceModelVersion = (modelId, version) =>
  del(`/source-models/${modelId}/versions/${version}`);

export const deleteSourceModel = (modelId, { cascade = false } = {}) =>
  del(`/source-models/${modelId}?cascade=${cascade ? "true" : "false"}`);

// ---- storage locations (Storage page) ----

// Read-only: lists model files in the STL folder that aren't in the library yet.
export const scanStlFolder = async () => {
  const r = await post("/source-models/scan");
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

// ---- download URLs (plain links; the browser handles the download) ----

export const bundle3mfUrl = (versionId) => `${API_BASE}/bundles/versions/${versionId}/download/3mf`;

export const bundleGcodeUrl = (versionId) => `${API_BASE}/bundles/versions/${versionId}/download/gcode`;

export const sourceModelDownloadUrl = (modelId, version) =>
  `${API_BASE}/source-models/${modelId}/versions/${version}/download`;
