// Default to whatever host the browser is actually using, not a hardcoded
// "localhost" — that breaks the moment this is viewed from a different
// machine than the one running Docker (e.g. a phone/laptop hitting a
// Raspberry Pi's LAN IP). VITE_API_BASE still overrides this when set.
const defaultApiBase = `${window.location.protocol}//${window.location.hostname}:4545`;
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

// The words to show for a failed request (or anything else that went wrong)
export const errorText = (e) => e.message || String(e);

// A request whose body is JSON
const jsonBody = (method, data) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(data),
});

// A request whose body is a form (files and text fields). Fields left undefined aren't sent.
const formBody = (method, fields) => {
  const form = new FormData();
  for (const [name, value] of Object.entries(fields)) if (value !== undefined) form.append(name, value);
  return { method, body: form };
};

// A delete. The API refuses deletes without confirm=true; the UI's own confirmation
// dialog is the real guard, so every delete is made after the user said yes.
const del = (path) => request(`${path}${path.includes("?") ? "&" : "?"}confirm=true`, { method: "DELETE" });
// A POST that sends nothing but the asking ("sync now", "connect")
const post = (path) => request(path, { method: "POST" });
// Notes, saved with the revision they were based on (a 409 answers with someone else's newer notes)
const notesBody = (notes, baseRevision) => jsonBody("PUT", { notes, base_revision: baseRevision });

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
  moonrakerUrl: p.moonraker_url || null, // where Farmhand reaches its Moonraker (set, else <IP>:7125)
  moonrakerUrlOverride: p.moonraker_url_override || null, // only what was set for it
  mainsailUrl: p.mainsail_url || null,
  hasMoonrakerApiKey: !!p.has_moonraker_api_key, // the key itself never comes back
  connectionType: p.connection_type || "moonraker", // "moonraker" (Klipper) | "prusalink" (Prusa Core One, MK4, XL...)
  prusalinkUrl: p.prusalink_url || null, // where Farmhand reaches its PrusaLink (set, else http://<IP>)
  prusalinkUrlOverride: p.prusalink_url_override || null,
  prusalinkUsername: p.prusalink_username || "maker",
  hasPrusalinkPassword: !!p.has_prusalink_password, // the password itself only comes from getPrusaLinkPassword
  cameraAddress: p.camera_address || null, // a camera Farmhand plays itself (a Buddy3D's): its IP, or an rtsp:// URL
  // its printer presets in the slicer, A to Z: [{ id, name, aliases, settingsCopiedFrom }]; settingsCopiedFrom: a copy's
  // original, whose printer settings it was copied with (null for one that isn't a copy, or got none)
  subPrinters: (p.sub_printers || []).map((s) => ({ ...s, settingsCopiedFrom: s.settings_copied_from || null })),
  defaultSubPrinterId: p.default_sub_printer_id ?? null, // the one its uploads start on (null: Farmhand guesses)
  // The 1500-hour service reminder Farmhand keeps: { state: waiting | off | ok | due, enabled, interval_hours,
  // hours_since, started_at, last_done: { done_at, hours, note } | null }
  service: p.service || {
    state: "waiting", enabled: true, interval_hours: 1500, hours_since: null, started_at: null, last_done: null,
    notes: "", notes_revision: 0, notes_updated_at: null,
  },
});

// A preview's address ends in ?r=<its revision> (when it was drawn; a 3MF version's never changes), so the address
// changes whenever the picture does and the browser can keep each one for good instead of asking again every time.

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

export const getPrinters = () => request("/printers");
const getBundle = (bundleId) => request(`/bundles/${bundleId}`);

// A project's own files of one kind ("cad" / "stl"): each with every version, newest first, with where to download it
// and its preview (null when none could be made)
const normalizeProjectFiles = (projectId, kind, files) =>
  (files || []).map((f) => ({
    id: f.id,
    name: f.name,
    printerId: f.printer_id ?? null, // a 3MF's: the printer it's for
    need: f.need ?? null, // an STL's: how many prints of it the project needs
    have: f.have ?? null, // and has
    component: f.component || null, // an STL's: the sub-component it's in ("Body/Fins"), or none
    versions: f.versions.map((v) => {
      const base = `${API_BASE}/projects/${projectId}/${kind}/${f.id}/versions/${v.version}`;
      return {
        v: v.version,
        filename: v.filename,
        size: v.size_bytes,
        note: v.note,
        date: fmtDate(v.uploaded_at),
        download: `${base}/download`,
        view: `${base}/view`, // opened in the browser (a PDF, a picture...), not saved
        preview: v.has_preview ? `${base}/preview?v=${encodeURIComponent(v.uploaded_at)}` : null,
        gcodeName: v.gcode_name || null, // a 3MF version's G-code, if it has one
        gcodeDownload: v.gcode_name ? `${base}/gcode` : null,
      };
    }),
  }));

// A project: its name, its own documents, CAD files, STLs and 3MFs, the models, 3MFs and printers from the rest of Farmhand it
// uses (their ids, in the order they were added), and its BOM (parts list): [{ id, name, need, have, link, note }].
export const normalizeProject = (p) => ({
  id: p.id,
  name: p.name,
  created: p.created_at,
  docFiles: normalizeProjectFiles(p.id, "doc", p.doc_files),
  cadFiles: normalizeProjectFiles(p.id, "cad", p.cad_files),
  stlFiles: normalizeProjectFiles(p.id, "stl", p.stl_files),
  threemfFiles: normalizeProjectFiles(p.id, "threemf", p.threemf_files),
  modelIds: p.source_model_ids || [],
  // id -> { need, have, component }: how many prints of each model it needs and has, and the sub-component it's in
  modelCounts: Object.fromEntries((p.source_models || []).map((m) => [m.id, { need: m.need, have: m.have, component: m.component || null }])),
  bundleIds: p.bundle_ids || [],
  printerIds: p.printer_ids || [],
  parts: p.parts || [],
});

export const fetchAll = async () => {
  const [printers, models, bundles, projects] = await Promise.all([
    getPrinters(),
    request("/source-models"),
    request("/bundles"),
    request("/projects"),
  ]);
  return {
    printers: printers.map(normalizePrinter),
    sourceModels: models.map(normalizeSourceModel),
    bundles: bundles.map(normalizeBundle),
    projects: projects.map(normalizeProject),
  };
};

export const fetchVersionSettings = async (versionId) => {
  const detail = await request(`/bundles/versions/${versionId}`);
  return detail.settings || {};
};

// ---- writes ----

// Projects: make one, rename it, delete it (the server answers a made or renamed project as it now stands)
export const createProject = (name) => request("/projects", jsonBody("POST", { name }));
export const renameProject = (id, name) => request(`/projects/${id}`, jsonBody("PATCH", { name }));
export const deleteProject = (id) => del(`/projects/${id}`);
// A project's own files, kind "doc", "cad", "stl" or "threemf": a new one (its version 1), a newer version of one, and deleting a version
// or the whole file. An STL also says whether it goes in Models too (inModels: true makes it a model there that the
// project uses; false keeps it the project's own) and the sub-component it goes in, if any (component: its folder,
// "Body/Fins"). Each answers the project as it now stands.
// A 3MF says which printer it's for (printerId), which then comes into the project too.
export const uploadProjectFile = ({ kind, projectId, file, note, inModels, component, printerId }) =>
  request(`/projects/${projectId}/${kind}`, formBody("POST", {
    file,
    note: note || undefined,
    in_models: kind === "stl" ? String(!!inModels) : undefined,
    component: kind === "stl" && component ? component : undefined,
    printer_id: kind === "threemf" && printerId != null ? String(printerId) : undefined,
  }));
export const uploadProjectFileVersion = ({ kind, projectId, fileId, file, note }) =>
  request(`/projects/${projectId}/${kind}/${fileId}/versions`, formBody("POST", { file, note: note || undefined }));
export const deleteProjectFileVersion = (kind, projectId, fileId, v) => del(`/projects/${projectId}/${kind}/${fileId}/versions/${v}`);
export const deleteProjectFile = (kind, projectId, fileId) => del(`/projects/${projectId}/${kind}/${fileId}`);
// A project's documents or CAD files ("doc" / "cad") put in this order: every one's id, first to last. Answers the project.
export const arrangeProjectFiles = (kind, projectId, ids) => request(`/projects/${projectId}/${kind}/order`, jsonBody("PUT", { ids }));

// Scan projects. A folder's subfolders, each as the project it would become:
// { path, folders: [{ name, path, files: { doc, cad, stl, threemf, gcode }, total, inFarmhand, error }] }
export const scanProjectFolder = async (path) => {
  const r = await request(`/projects/scan?path=${encodeURIComponent(path)}`);
  return {
    path: r.path,
    folders: r.folders.map((f) => ({ name: f.name, path: f.path, files: f.files, total: f.total, inFarmhand: f.in_farmhand, error: f.error })),
  };
};
// One folder made into a project, its files copied in: { projectId, name, files, warnings }. 409 if the name's taken.
export const importProjectFolder = async (path) => {
  const r = await request("/projects/import", jsonBody("POST", { path }));
  return { projectId: r.project_id, name: r.name, files: r.files, warnings: r.warnings };
};
// Every project file against the disk (changes nothing): { projects, filesChecked, root, error, problems: [{ projectId,
// project, kind, fileId, version, filename, path, problem }], problemsTotal, unknown: [paths], unknownTotal }
export const checkProjectFiles = async () => {
  const r = await request("/projects/check");
  return {
    projects: r.projects, filesChecked: r.files_checked, root: r.root, error: r.error,
    problems: r.problems.map((p) => ({
      projectId: p.project_id, project: p.project, kind: p.kind, fileId: p.file_id, version: p.version,
      filename: p.filename, path: p.path, problem: p.problem,
    })),
    problemsTotal: r.problems_total, unknown: r.unknown, unknownTotal: r.unknown_total,
  };
};
// A model from the Models page: put in a project, or taken out of it (the model itself stays)
export const addProjectModel = (projectId, modelId) => request(`/projects/${projectId}/source-models/${modelId}`, { method: "PUT" });
export const removeProjectModel = (projectId, modelId) => request(`/projects/${projectId}/source-models/${modelId}`, { method: "DELETE" });
// A 3MF from the rest of Farmhand (its printer comes too), and a printer: put in a project, or taken out
export const addProjectBundle = (projectId, bundleId) => request(`/projects/${projectId}/bundles/${bundleId}`, { method: "PUT" });
export const removeProjectBundle = (projectId, bundleId) => request(`/projects/${projectId}/bundles/${bundleId}`, { method: "DELETE" });
export const addProjectPrinter = (projectId, printerId) => request(`/projects/${projectId}/printers/${printerId}`, { method: "PUT" });
export const removeProjectPrinter = (projectId, printerId) => request(`/projects/${projectId}/printers/${printerId}`, { method: "DELETE" });
// A project's BOM: a part added, changed (only the fields given) or removed, each answering the project; and a BOM CSV
// uploaded, its parts added to the list or replacing it, answering { project, added }
export const addProjectPart = (projectId, { name, need, have, link, note }) =>
  request(`/projects/${projectId}/parts`, jsonBody("POST", { name, need, have, link: link || null, note: note || null }));
export const updateProjectPart = (projectId, partId, changes) => request(`/projects/${projectId}/parts/${partId}`, jsonBody("PATCH", changes));
export const deleteProjectPart = (projectId, partId) => del(`/projects/${projectId}/parts/${partId}`);
// How many prints of an STL a project needs and has, and the sub-component it's in ({ component: "Body/Fins" }, or null
// for none): a model from Models ("model") or one of its own ("stl"). Only what's given changes.
export const setProjectStlCounts = (projectId, kind, id, counts) =>
  request(`/projects/${projectId}/${kind === "model" ? "source-models" : "stl"}/${id}`, jsonBody("PATCH", counts));
// A project 3MF version's G-code: uploaded (replacing one it had), and sent to the 3MF's printer (it starts printing)
export const uploadProjectGcode = ({ projectId, fileId, v, gcode }) =>
  request(`/projects/${projectId}/threemf/${fileId}/versions/${v}/gcode`, formBody("PUT", { gcode }));
export const sendProjectGcode = (projectId, fileId, v) => post(`/projects/${projectId}/threemf/${fileId}/versions/${v}/print`);
export const uploadBom = ({ projectId, file, replace }) =>
  request(`/projects/${projectId}/parts/bom`, formBody("POST", { file, replace: String(!!replace) }));

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

// The range a scan starts with: the /24 of the network the server is on ("192.168.10.0/24"), or "" when it can't tell
export const getDiscoverRange = async () => (await request("/printers/discover/range")).cidr || "";

// The printers in a network range (e.g. "192.168.1.0/24") that aren't in Farmhand yet. Nothing is added; `signal`
// lets the dialog stop waiting (the scan itself runs to its end on the server).
export const discoverPrinters = async (cidr, { signal } = {}) =>
  (await request(`/printers/discover?cidr=${encodeURIComponent(cidr)}`, { signal })).map((f) => ({
    ip: f.ip,
    hostname: f.hostname || "",
    connectionType: f.connection_type,
    address: f.address,
    webUrl: f.web_url || null,
    firmware: f.firmware || null, // "Klipper" | "Kalico" | "Prusa"; null when it wouldn't say
    version: f.version || null,
    state: f.state || null,
    needsApiKey: !!f.needs_api_key, // it wants its login: Moonraker's API key, or PrusaLink's password
    link: f.link || null, // how `ip` reached it: "wired" | "wireless"; null when it couldn't tell
    wiredIp: f.wired_ip || null, // a printer on both is found once, at its wired IP, with both of these
    wirelessIp: f.wireless_ip || null,
    // the decommissioned printer in Farmhand at one of its addresses: picking it brings that one back
    decommissionedId: f.decommissioned_id ?? null,
    decommissionedName: f.decommissioned_name || null,
  }));

// The connection (Mainsail / Moonraker or PrusaLink) can be given straight away, with the same fields as updatePrinter
export const createPrinter = ({
  name, kind, wiredIp, wirelessIp, connectionType, moonrakerUrl, moonrakerApiKey, prusalinkUrl, prusalinkUsername, prusalinkPassword,
  cameraAddress,
}) =>
  request("/printers", jsonBody("POST", {
    name,
    kind: kind || null,
    wired_ip: wiredIp || null,
    wireless_ip: wirelessIp || null,
    connection_type: connectionType || "moonraker",
    ...(moonrakerUrl ? { moonraker_url: moonrakerUrl } : {}),
    ...(moonrakerApiKey ? { moonraker_api_key: moonrakerApiKey } : {}),
    ...(prusalinkUrl ? { prusalink_url: prusalinkUrl } : {}),
    ...(prusalinkUsername ? { prusalink_username: prusalinkUsername } : {}),
    ...(prusalinkPassword ? { prusalink_password: prusalinkPassword } : {}),
    ...(cameraAddress ? { camera_address: cameraAddress } : {}),
  }));

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

// moonrakerUrl: blank = the default (<IP>:7125). moonrakerApiKey: undefined keeps the saved key, "" removes it.
// connectionType: "moonraker" | "prusalink". prusalinkUrl: blank = http://<IP>. prusalinkPassword works like the API key.
// cameraAddress: blank removes the camera.
export const updatePrinter = (
  id,
  {
    name, kind, wiredIp, wirelessIp, decommissioned, moonrakerUrl, moonrakerApiKey, connectionType, prusalinkUrl, prusalinkUsername,
    prusalinkPassword, cameraAddress,
  },
) =>
  // Blank optional fields are sent as null so they actually clear
  request(`/printers/${id}`, jsonBody("PATCH", {
    name,
    kind: kind || null,
    wired_ip: wiredIp || null,
    wireless_ip: wirelessIp || null,
    decommissioned: !!decommissioned,
    ...(moonrakerUrl !== undefined ? { moonraker_url: moonrakerUrl || null } : {}),
    ...(moonrakerApiKey !== undefined ? { moonraker_api_key: moonrakerApiKey } : {}),
    ...(connectionType !== undefined ? { connection_type: connectionType } : {}),
    ...(prusalinkUrl !== undefined ? { prusalink_url: prusalinkUrl || null } : {}),
    ...(prusalinkUsername !== undefined ? { prusalink_username: prusalinkUsername } : {}),
    ...(prusalinkPassword !== undefined ? { prusalink_password: prusalinkPassword } : {}),
    ...(cameraAddress !== undefined ? { camera_address: cameraAddress || null } : {}),
  }));

// Only a decommissioned printer with no 3MF files kept for it (409 otherwise, saying why)
export const deletePrinter = (id) => del(`/printers/${id}`);

// ---- a printer's printer profiles: its printer presets in the slicer (found from its 3MFs, or added here). Each
// resolves to the whole printer as it now stands. 409 when the printer already has one by that name. ----
const subPrinterPath = (printerId, subPrinterId) => `/printers/${printerId}/sub-printers/${subPrinterId}`;
export const addSubPrinter = (printerId, name) => request(`/printers/${printerId}/sub-printers`, jsonBody("POST", { name }));
// a new printer profile with a copy of its parts and printer settings, called `name` (its 3MFs and being the default
// stay with the original)
export const copySubPrinter = (printerId, subPrinterId, name) =>
  request(`${subPrinterPath(printerId, subPrinterId)}/copy`, jsonBody("POST", { name }));
export const renameSubPrinter = (printerId, subPrinterId, name) =>
  request(subPrinterPath(printerId, subPrinterId), jsonBody("PATCH", { name }));
// the one its uploads start on, whatever preset a 3MF was sliced with; null: none (Farmhand guesses from the preset)
export const setDefaultSubPrinter = (printerId, subPrinterId) =>
  request(`/printers/${printerId}/default-sub-printer`, jsonBody("PUT", { sub_printer_id: subPrinterId }));
// its 3MFs stay, with no printer profile; its parts go
export const deleteSubPrinter = (printerId, subPrinterId) => del(subPrinterPath(printerId, subPrinterId));

// A printer profile's parts (its Printer parts page): [{ id, part, make, model, installedOn: "2026-08-14" | null, note,
// inName }].
// Saving resolves to the whole list as it now stands.
const normalizePart = (p) => ({
  id: p.id, part: p.part, make: p.make || "", model: p.model || "", installedOn: p.installed_on || null, note: p.note || "",
  inName: !!p.in_name, // ticked "Add to name"
});
const partBody = ({ part, make, model, installedOn, note, inName }) => ({
  part, make: make || null, model: model || null, installed_on: installedOn || null, note: note || null, in_name: !!inName,
});
const partsPath = (printerId, subPrinterId) => `${subPrinterPath(printerId, subPrinterId)}/parts`;
const partsList = async (call) => (await call).map(normalizePart);
export const getSubPrinterParts = (printerId, subPrinterId) => partsList(request(partsPath(printerId, subPrinterId)));
// A copied printer profile's printer settings, as its original had them: { copiedFrom, fromFile, copiedAt, settings }
export const getSubPrinterSettingsCopy = async (printerId, subPrinterId) => {
  const r = await request(`${subPrinterPath(printerId, subPrinterId)}/settings-copy`);
  return { copiedFrom: r.copied_from, fromFile: r.from_file || null, copiedAt: r.copied_at || null, settings: r.settings || {} };
};
// The whole list at once, as the page was edited: a part with an id is changed, one without is added, and one left out
// is removed (`removes`: the list leaves some out, which the API wants confirmed). All of it, or nothing.
export const saveSubPrinterParts = (printerId, subPrinterId, parts, removes) =>
  partsList(request(`${partsPath(printerId, subPrinterId)}${removes ? "?confirm=true" : ""}`, jsonBody("PUT", parts.map((p) => ({ id: p.id ?? null, ...partBody(p) })))));

// ---- a PrusaLink printer (Prusa Core One...): live status and sending it a print. Its history, statistics, service
// and maintenance use the same calls as a Moonraker printer's (below); its maintenance is kept in Farmhand. ----

// { reachable, error, error_kind, state, printer_type, firmware, temps: { temp_nozzle, target_nozzle, temp_bed,
//   target_bed }, job: { id, state, file, progress, time_printing, time_remaining } | null, last_sync_at, totals }
// Asking also brings Farmhand's record of its prints up to date.
export const getPrusaLinkStatus = (printerId) => request(`/printers/${printerId}/prusalink`);
// The PrusaLink password saved for it (null when none is): asked for only when it's to be shown
export const getPrusaLinkPassword = async (printerId) => (await request(`/printers/${printerId}/prusalink/password`)).password;
// A sliced .bgcode / .gcode: put on the printer's USB drive and printed. 409 while the printer is busy.
export const sendPrint = (printerId, file) => request(`/printers/${printerId}/prusalink/print`, formBody("POST", { file }));

// ---- a printer's Moonraker: connection, print history (Farmhand's copy), statistics, maintenance ----
// A printer that can't be reached answers 502 with { detail, kind } (no_address | unreachable | unauthorized | ...).

// { reachable, klippy_state, moonraker_version, error, error_kind, print: { state: printing | paused, file, progress
//   (0-100), print_duration, time_remaining, extruder, heater_bed } | null, last_sync_at, totals, ... }
export const getMoonrakerStatus = (printerId) => request(`/printers/${printerId}/moonraker`);
export const syncPrinterHistory = (printerId) => post(`/printers/${printerId}/moonraker/sync`);
export const getPrintStats = (printerId) => request(`/printers/${printerId}/print-stats`);
// A printer's cameras as set up in Mainsail, for the Monitor page: { webcams: [{ name, service, mjpeg, stream_url,
// snapshot_url, flip_horizontal, flip_vertical, rotation, aspect_ratio }], error }. Never fails: error says why there are none.
// ...and board: the computer a Klipper printer runs on, { name: "Pi 4" | "CM4" | ..., model, memory_gb }, or null
export const getWebcams = (printerId) => request(`/printers/${printerId}/webcams`);
// How far along the print running now is: { state: "printing" | "paused" | null, progress: 0-100 | null, file, error }
export const getPrintProgress = (printerId) => request(`/printers/${printerId}/progress`);

// this browser's time zone ("Europe/Amsterdam"), or "" if it can't say
const timeZone = (() => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch {
    return "";
  }
})();
// { meter: { sensor, energy_kwh, taken_at, first_reading_at } | null, print_total_kwh, print_jobs_kwh,
//   months: [{ key: "2026-10", prints, print_count, whole, partial }] } — totalled by the server in this browser's
//   time zone (a year is its months added up)
export const getEnergy = (printerId) =>
  request(`/printers/${printerId}/energy${timeZone ? `?tz=${encodeURIComponent(timeZone)}` : ""}`);

// The Farm cost page's filament: { printers: [{ printer_id, months: [{ key: "2026-10", prints, grams, filament_cost,
// unweighed, uncosted }] }] }, months newest first, totalled in this browser's time zone; records: { folder, problem,
// saved: [file names, newest first] }, where each month's record is saved once it's over
export const getFarmCost = () => request(`/farm-cost${timeZone ? `?tz=${encodeURIComponent(timeZone)}` : ""}`);

// Where each month's Farm cost record is saved (Settings): { path, isDefault, defaultPath, status: { exists,
// writable, markerOk, ready } }. setFarmCostLocation(null) goes back to the default; a folder that can't be used is
// refused with the reason.
const normalizeFarmCostLocation = (l) => ({
  path: l.path,
  isDefault: l.is_default,
  defaultPath: l.default_path,
  status: { exists: l.status.exists, writable: l.status.writable, markerOk: l.status.marker_ok, ready: l.status.ready },
});
export const getFarmCostLocation = async () => normalizeFarmCostLocation(await request("/farm-cost/location"));
export const setFarmCostLocation = async (path) =>
  normalizeFarmCostLocation(await request("/farm-cost/location", jsonBody("PUT", { path })));

// status: "" (all) | "completed" | "failed" | "cancelled" | "error" | ...; q: words that must all be in the file name.
// Each job has filament_grams (the filament used in grams; null when no density or slicer estimate is known),
// filament_cost (null when there's no price for it) and filament_cost_detail: { cost, grams, cost_per_kg,
// density, diameter, source: "gcode" | "3mf", filename, bundle_id, version_id, version } | null; energy_cost: its
// energy_kwh at the Power page's price per kWh (null without either); total_cost: filament_cost + energy_cost (the
// filament cost alone without an energy cost; null or 0 when the filament cost is). The answer also has
// energy_price_per_kwh.
export const getPrintJobs = (printerId, { limit = 25, offset = 0, status = "", q = "" } = {}) => {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (status) params.set("status", status);
  if (q.trim()) params.set("q", q.trim());
  if (timeZone) params.set("tz", timeZone); // which month a print's energy is priced in
  return request(`/printers/${printerId}/print-jobs?${params}`);
};

// The 1500-hour service lives in Farmhand. Both resolve to the printer as it now stands.
export const serviceDone = (printerId, { note }) => request(`/printers/${printerId}/service/done`, jsonBody("POST", { note }));
export const setServiceEnabled = (printerId, enabled) => request(`/printers/${printerId}/service`, jsonBody("PATCH", { enabled }));
// Notes kept with the service: the same rules as other notes (a save names the revision it started from; 409 if moved
// on). Resolves to the printer (as .printer); NotesSection reads `notes` / `notes_revision` from what onSave returns, hence the reshape.
export const saveServiceNotes = async ({ printerId, notes, baseRevision }) => {
  const p = await request(`/printers/${printerId}/service/notes`, notesBody(notes, baseRevision));
  return { notes: p.service.notes, notes_revision: p.service.notes_revision, printer: p };
};

// Maintenance lives in the printer's Moonraker, in Mainsail's own format: Mainsail shows the same list. A PrusaLink
// printer's is kept in Farmhand, in the same format (no filament reminders: it doesn't report filament use).
// reminder: { type: null | "one-time" | "repeat", filament / printtime / date: { bool, value } } in metres / hours / days
export const getMaintenance = (printerId) => request(`/printers/${printerId}/maintenance`);
export const addMaintenance = (printerId, { name, note, reminder }) =>
  request(`/printers/${printerId}/maintenance`, jsonBody("POST", { name, note, reminder }));
export const updateMaintenance = (printerId, entryId, { name, note, reminder }) =>
  request(`/printers/${printerId}/maintenance/${encodeURIComponent(entryId)}`, jsonBody("PUT", { name, note, reminder }));
export const performMaintenance = (printerId, entryId, { note }) =>
  request(`/printers/${printerId}/maintenance/${encodeURIComponent(entryId)}/done`, jsonBody("POST", { note }));
export const deleteMaintenance = (printerId, entryId) => del(`/printers/${printerId}/maintenance/${encodeURIComponent(entryId)}`);

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

// ---- notes about a printer (the same rules as a model's: a save names the revision it started from) ----
export const savePrinterNotes = ({ printerId, notes, baseRevision }) =>
  request(`/printers/${printerId}/notes`, notesBody(notes, baseRevision));

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
  project: normalizeLocation(r.project), // project files: each project's own files (its CAD files)
  outside: r.outside, // { stl, threemf, project }: versions whose files are still outside the selected locations
});

export const getStorageSettings = async () => normalizeStorage(await request("/settings/storage"));

// Only the locations passed are changed; null resets that one to its default.
export const saveStorageSettings = async ({ stlPath, threemfPath, projectPath }) => {
  const body = {};
  if (stlPath !== undefined) body.stl_path = stlPath;
  if (threemfPath !== undefined) body.threemf_path = threemfPath;
  if (projectPath !== undefined) body.project_path = projectPath;
  return normalizeStorage(await request("/settings/storage", jsonBody("PUT", body)));
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
  normalizeBrowse(await request("/settings/storage/folders", jsonBody("POST", { parent, name })));

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

// The save location: one place on the NAS everything goes in. { address (null until set), folders: { stl, threemf,
// project, farmCost, config } }
const normalizeSaveLocation = (r) => ({
  address: r.address,
  folders: { stl: r.folders.stl, threemf: r.folders.threemf, project: r.folders.project, farmCost: r.folders.farm_cost, config: r.folders.config },
});
export const getSaveLocation = async () => normalizeSaveLocation(await request("/settings/storage/save-location"));
// Connects to the address (reusing the share already there) and uses or makes STL, 3MF, Projects, Farm cost and
// Farmhand Configs inside it. configChoice: what's in Farmhand Configs when it already holds saved settings (ask to
// load or replace them), else null. A blank password keeps the saved one.
export const setSaveLocation = async ({ address, username, password }) => {
  const r = await request(
    "/settings/storage/save-location",
    jsonBody("PUT", { address, username: username || null, ...(password ? { password } : {}) }),
  );
  return { ...normalizeSaveLocation(r), configChoice: normalizeFound(r.config_choice) };
};

export const getShares = async () => {
  const r = await request("/settings/storage/shares");
  return { shares: r.shares.map(normalizeShare), capability: r.capability };
};

// Mounts the share first and only saves it if that worked, so errors here are the real reason.
export const createShare = async (data) => normalizeShare(await request("/settings/storage/shares", jsonBody("POST", data)));
export const updateShare = async (id, data) =>
  normalizeShare(await request(`/settings/storage/shares/${id}`, jsonBody("PATCH", data)));
export const reconnectShare = async (id) =>
  normalizeShare(await post(`/settings/storage/shares/${id}/connect`));
export const deleteShare = (id) => del(`/settings/storage/shares/${id}`);

export const migrateStorage = async () => {
  const r = await post("/settings/storage/migrate");
  return { movedStl: r.moved_stl, movedThreemf: r.moved_threemf, movedProject: r.moved_project || 0, missing: r.missing, failed: r.failed };
};

// Redraw one version's preview from its file with the current renderer. Resolves to { updated }.
export const redrawPreview = ({ modelId, version }) =>
  post(`/source-models/${modelId}/versions/${version}/thumbnail`);

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

export const saveConfigNow = () => post("/settings/config/save-now");
// Save all: every setting, printer and model written to the settings folder now. With no folder chosen, Farmhand picks
// "farmhand configs" beside the STL folder; one already holding settings needs a choice first (needsChoice, found),
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
  };
};
export const restoreConfig = async () => normalizeRestore(await post("/settings/config/restore"));

// ---- scanning the STL folder for files added from outside Farmhand ----

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
