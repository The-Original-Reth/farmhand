// Projects: their own files, the models, 3MFs and printers they use, their BOM, and Scan projects.
import { API_BASE, del, fmtDate, formBody, jsonBody, post, request } from "./client.js";

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

// Scan projects: every folder in the project files folder that isn't one of this Farmhand's projects brought in, its files
// used where they are (another Farmhand's, from its records, or one dropped in by hand):
// { imported: [{ projectId, name, files, warnings }], skipped: [{ name, reason }] }
export const scanProjectsFolder = async () => {
  const r = await request("/projects/scan-projects-folder", { method: "POST" });
  return {
    // repaired: one here already, rebuilt from another Farmhand's record of it (it had come in as its folder's number)
    imported: r.imported.map((p) => ({ projectId: p.project_id, name: p.name, files: p.files, warnings: p.warnings, repaired: !!p.repaired })),
    skipped: r.skipped,
    // the models and 3MFs another Farmhand sharing the folders has, brought in first (by name), and ones left out
    models: r.models || [],
    threemfs: r.threemfs || [],
    librarySkipped: r.library_skipped || [],
  };
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
