// The HTTP client every call goes through: where the API is, the request and its error, and request bodies.

// The plugin's own API, relative to its page: /plugins/stream/api inside Farmhand, /api opened on the plugin itself.
// (The page only ever talks to its own plugin, never to Farmhand or the cameras.)
export const API_BASE = "api";

export async function request(path, options = {}) {
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
export const jsonBody = (method, data) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(data),
});

// A request whose body is a form (files and text fields). Fields left undefined aren't sent.
export const formBody = (method, fields) => {
  const form = new FormData();
  for (const [name, value] of Object.entries(fields)) if (value !== undefined) form.append(name, value);
  return { method, body: form };
};

// A delete. The API refuses deletes without confirm=true; the UI's own confirmation
// dialog is the real guard, so every delete is made after the user said yes.
export const del = (path) => request(`${path}${path.includes("?") ? "&" : "?"}confirm=true`, { method: "DELETE" });

// A POST that sends nothing but the asking ("sync now", "connect")
export const post = (path) => request(path, { method: "POST" });

// Notes, saved with the revision they were based on (a 409 answers with someone else's newer notes)
export const notesBody = (notes, baseRevision) => jsonBody("PUT", { notes, base_revision: baseRevision });

export const fmtDate = (iso) =>
  iso ? new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "—";

// ---- normalizers: API shape -> the shape the UI components use ----

// this browser's time zone ("Europe/Amsterdam"), or "" if it can't say
export const timeZone = (() => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch {
    return "";
  }
})();
// "?tz=<this browser's time zone>", or nothing when the browser doesn't say
export const tzQuery = timeZone ? `?tz=${encodeURIComponent(timeZone)}` : "";

// A chosen folder's state, as the API answers it for every "where things are saved" setting
export const normalizeFolderStatus = (s) =>
  s && { exists: s.exists, writable: s.writable, markerOk: s.marker_ok, ready: s.ready };
// A folder setting with a default: { path, isDefault, defaultPath, status }
export const normalizeFolderLocation = (l) => ({
  path: l.path, isDefault: l.is_default, defaultPath: l.default_path, status: normalizeFolderStatus(l.status),
});
