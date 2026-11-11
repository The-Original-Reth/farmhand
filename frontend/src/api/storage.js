// The Storage page: where files go, the folder picker, network shares and the save location.
import { jsonBody, normalizeFolderLocation, normalizeFolderStatus, post, request } from "./client.js";
import { normalizeFound } from "./settings.js";

// a file root also says how full its disk is
const normalizeLocation = (l) => ({
  ...normalizeFolderLocation(l),
  status: {
    ...normalizeFolderStatus(l.status),
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

// The save location: one place on the NAS everything goes in. { address (null until set), share (its share as the
// shares list has one, null until set), capability (may this container mount shares), folders: { stl, threemf, project,
// farmCost, stream, config } }
const normalizeSaveLocation = (r) => ({
  address: r.address,
  share: r.share ? normalizeShare(r.share) : null,
  capability: r.capability || null,
  folders: { stl: r.folders.stl, threemf: r.folders.threemf, project: r.folders.project, farmCost: r.folders.farm_cost, stream: r.folders.stream, config: r.folders.config },
});

export const getSaveLocation = async () => normalizeSaveLocation(await request("/settings/storage/save-location"));

// Connects to the address (reusing the share already there) and uses or makes STL, 3MF, Projects, Farm cost and
// farmhand-configs inside it. configChoice: what's in farmhand-configs when it already holds saved settings (ask to
// load or replace them), else null. A blank password keeps the saved one.
// domain and version (Advanced): the workgroup, and the SMB / NFS version ("" = worked out by itself); left out, the
// share's stay as they are
export const setSaveLocation = async ({ address, username, password, domain, version }) => {
  const r = await request(
    "/settings/storage/save-location",
    jsonBody("PUT", {
      address,
      username: username || null,
      ...(password ? { password } : {}),
      ...(domain !== undefined ? { domain } : {}),
      ...(version !== undefined ? { version } : {}),
    }),
  );
  return { ...normalizeSaveLocation(r), configChoice: normalizeFound(r.config_choice) };
};

export const getShares = async () => {
  const r = await request("/settings/storage/shares");
  return { shares: r.shares.map(normalizeShare), capability: r.capability };
};

export const reconnectShare = async (id) =>
  normalizeShare(await post(`/settings/storage/shares/${id}/connect`));

export const migrateStorage = async () => {
  const r = await post("/settings/storage/migrate");
  return { movedStl: r.moved_stl, movedThreemf: r.moved_threemf, movedProject: r.moved_project || 0, missing: r.missing, failed: r.failed };
};

// Redraw one version's preview from its file with the current renderer. Resolves to { updated }.
export const redrawPreview = ({ modelId, version }) =>
  post(`/source-models/${modelId}/versions/${version}/thumbnail`);

// ---- settings: appearance + display preferences, kept on the server and copied to a network folder ----
