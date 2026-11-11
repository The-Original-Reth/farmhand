// The mockup's own core: the sample farm (one object, kept in memory; resetFarm starts it over), how routes are
// added, and the helpers that shape data like the real API, which every part of the mockup uses.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { buildFarm, DAY, FIXTURES, iso, jobTotals } from "./data.js";

export const PREFIX = "/mock-api";
export const nowUnix = () => Math.floor(Date.now() / 1000);

export class HttpError extends Error {
  constructor(status, detail, extra = {}) {
    super(detail);
    this.status = status;
    this.extra = extra;
  }
}
export const NO_MOONRAKER = "This printer has no IP address or Moonraker address set.";
export const notInMockup = (what) => new HttpError(501, `${what} isn't available in the mockup: it needs the real Farmhand backend.`);

// A fresh mockup: the farm, the routes (none yet: each part in routes/ adds its own), and the helpers
export function createCore() {
  const farm = buildFarm();
  const routes = [];
  const on = (method, pattern, handler) => {
    const keys = [];
    const re = new RegExp(`^${pattern.replace(/:(\w+)/g, (_, k) => (keys.push(k), "([^/]+)"))}$`);
    routes.push({ method, re, keys, handler });
  };

  // ------------------------------------------------------------------ helpers shaping data like the real API
  const printer = (id) => farm.printers.find((p) => p.id === Number(id)) || fail404("Printer not found");
  const model = (id) => farm.models.find((m) => m.id === Number(id)) || fail404("Source model not found");
  const bundle = (id) => farm.bundles.find((b) => b.id === Number(id)) || fail404("Bundle not found");
  const version = (id) => {
    for (const b of farm.bundles) {
      const v = b.versions.find((x) => x.id === Number(id));
      if (v) return { b, v };
    }
    return fail404("Bundle version not found");
  };
  // a delete has to say confirm=true, as the real API asks (routers/common.py require_confirm), checked first
  function requireConfirm(q, detail = "Deleting is permanent — pass confirm=true to proceed") {
    if (q.get("confirm") !== "true") throw new HttpError(409, detail);
  }
  function fail404(detail) {
    throw new HttpError(404, detail);
  }

  const totalsFor = (p) => jobTotals(farm.jobs[p.id] || []);
  const synced = (p) => farm.connections[p.id] || {};
  const syncedTotals = (p) => p.prusalink ? { ...totalsFor(p), total_filament_used: null } : (p.moonraker && (p.moonraker.reachable || synced(p).last_sync_at || farm.jobs[p.id]) ? totalsFor(p) : null);
  const ipOf = (p) => p.wired_ip || p.wireless_ip; // wired preferred
  const moonrakerUrl = (p) => p.moonraker_url_override || (ipOf(p) ? `http://${ipOf(p)}:7125` : null);
  const mainsailUrl = (p) => { const u = moonrakerUrl(p); return u ? `http://${new URL(u).hostname}/` : null; };
  const prusalinkUrl = (p) => !p.prusalink ? null : p.prusalink.url || (ipOf(p) ? `http://${ipOf(p)}` : null);

  const service = (p) => {
    const notes = { notes: p.serviceNotes || "", notes_revision: p.serviceNotesRevision ?? 0, notes_updated_at: p.serviceNotesUpdatedAt ?? null };
    if (p.serviceHoursSince == null) {
      return { state: "waiting", enabled: true, interval_hours: 1500, hours_since: null, started_at: null, last_done: null, ...notes };
    }
    const enabled = p.serviceEnabled !== false;
    const last = (p.serviceHistory || []).slice(-1)[0];
    return {
      state: !enabled ? "off" : p.serviceHoursSince >= 1500 ? "due" : "ok",
      enabled, interval_hours: 1500, hours_since: p.serviceHoursSince,
      started_at: iso(last ? farm.now - last.hoursAgoDays * DAY : farm.now - 120 * DAY),
      last_done: last ? { done_at: iso(last.doneAt ?? farm.now - last.hoursAgoDays * DAY), printtime: 0, hours: last.hours, note: last.note } : null,
      ...notes,
    };
  };

  const printerOut = (p) => ({
    id: p.id, name: p.name, kind: p.kind, wired_ip: p.wired_ip, wireless_ip: p.wireless_ip, decommissioned: p.decommissioned,
    created_at: p.created_at, notes: p.notes || "", notes_revision: p.notesRevision ?? 0,
    notes_updated_at: p.notesUpdatedAt ?? null,
    moonraker_url: moonrakerUrl(p), moonraker_url_override: p.moonraker_url_override || null, mainsail_url: mainsailUrl(p),
    has_moonraker_api_key: !!p.apiKey, service: service(p),
    connection_type: p.prusalink ? "prusalink" : "moonraker", prusalink_url: prusalinkUrl(p),
    prusalink_url_override: p.prusalink?.url || null, prusalink_username: p.prusalink?.username || null,
    has_prusalink_password: !!p.prusalink?.hasPassword, camera_address: p.cameraAddress || null,
    sub_printers: farm.subPrinters.filter((s) => s.printer_id === p.id).sort((a, b) => a.name.localeCompare(b.name)).map(({ id, name, aliases, settings_copy }) => ({ id, name, aliases: aliases || [], settings_copied_from: settings_copy?.copied_from || null })),
    default_sub_printer_id: p.defaultSubPrinterId ?? null,
  });
  const modelOut = (m) => ({
    id: m.id, name: m.name, file_type: m.file_type, created_at: m.created_at, notes: m.notes, notes_revision: m.notes_revision,
    notes_updated_at: m.notes_updated_at,
    versions: m.versions.map((v) => ({ id: v.id, version: v.version, file_path: v.file_path, thumbnail_path: v.thumbnail_path, note: v.note, uploaded_at: v.uploaded_at })),
  });
  const versionOut = (v) => {
    const { thumb, ...rest } = v;
    const sub = farm.subPrinters.find((s) => s.id === v.sub_printer_id);
    return { ...rest, sub_printer_id: sub ? sub.id : null, sub_printer_name: sub ? sub.name : null };
  };
  const versionDetail = (v) => ({ ...versionOut(v), settings: farm.versionSettings[v.id] || {} });
  const bundleOut = (b) => ({
    id: b.id, printer_id: b.printer_id, created_at: b.created_at,
    source_models: b.source_model_ids.map((id) => farm.models.find((m) => m.id === id)).filter(Boolean).map(modelOut),
    versions: b.versions.map(versionOut), starred_version_id: b.starred_version_id,
    notes: b.notes, notes_revision: b.notes_revision, notes_updated_at: b.notes_updated_at,
  });

  // Notes saves follow the real rules: a save based on an old revision is refused with 409 and the current text
  const saveNotes = (owner, body, fields = { text: "notes", rev: "notes_revision", at: "notes_updated_at" }) => {
    const current = owner[fields.rev] ?? 0;
    if (body.base_revision !== current) {
      throw new HttpError(409, "These notes were changed by someone else while you were editing.", {
        current: { notes: owner[fields.text] || "", notes_revision: current, notes_updated_at: owner[fields.at] || null },
      });
    }
    const text = String(body.notes ?? "").replace(/\r\n?/g, "\n").replace(/^\n+/, "").trimEnd();
    if (!text && current === 0) return;
    owner[fields.text] = text;
    owner[fields.rev] = current + 1;
    owner[fields.at] = iso(nowUnix());
  };

  // A Klipper printer Farmhand can't reach answers 502, as the real API does
  const reachMoonraker = (p) => {
    if (!p.moonraker) throw new HttpError(502, NO_MOONRAKER, { kind: "no_address" });
    if (!p.moonraker.reachable) throw new HttpError(502, p.moonraker.error, { kind: p.moonraker.error_kind });
  };
  // The print a printer has running now, if any
  const runningJob = (p) => (farm.jobs[p.id] || []).find((j) => j.status === "in_progress");
  // The running job moves on with the clock and finishes once its estimate is up; the printer then shows FINISHED.
  const liveJob = (p) => {
    const job = runningJob(p);
    if (job) {
      job.printS = Math.min(job.estimated, nowUnix() - job.start);
      job.totalS = job.printS;
      if (job.printS >= job.estimated) {
        job.status = "completed";
        p.prusalink.finished = job;
      }
    }
    return job && job.status === "in_progress" ? job : null;
  };
  const location = (path) => ({
    path, default_path: path.includes("models") ? "/data/storage/source_models" : /projects$/i.test(path) ? projectsDefault() : "/data/storage/bundles", is_default: false,
    status: { exists: true, writable: true, marker_ok: true, ready: true, free_bytes: 2.1e12, total_bytes: 4e12, separate_volume: true },
  });
  // project files with none chosen: "Projects" beside the STL folder once that's on the NAS (as the server does)
  const projectsDefault = () =>
    farm.storage.stl.startsWith("/data/storage/") ? "/data/storage/projects" : farm.storage.stl.replace(/\/[^/]*$/, "") + "/Projects";
  const capability = { ok: true, smb: true, nfs: true, message: null, smb_message: null, nfs_message: null };
  const png = (slug) => (slug ? readFileSync(join(FIXTURES, "thumbs", `${slug.startsWith("stl-") ? slug : `3mf-${slug}`}.png`)) : null);
  // a fresh sample farm, e.g. after trying deletes (the same object: every part keeps using it)
  const resetFarm = () => {
    for (const key of Object.keys(farm)) delete farm[key];
    Object.assign(farm, buildFarm());
  };
  return { farm, routes, on, printer, model, bundle, version, requireConfirm, fail404, totalsFor, synced, syncedTotals, ipOf, moonrakerUrl, mainsailUrl, prusalinkUrl, service, printerOut, modelOut, versionOut, versionDetail, bundleOut, saveNotes, liveJob, runningJob, reachMoonraker, location, projectsDefault, capability, png, resetFarm };
}
