// The mockup's backend: a Vite plugin that answers the web UI's API calls under /mock-api from the sample farm in
// data.js, in exactly the shapes the real FastAPI backend uses. Changes (notes, stars, maintenance...) are kept in
// memory until the mockup restarts. Things that need real files or hardware (uploads, scanning, NAS mounting) answer
// with a plain "not in the mockup" message. Only loaded by `npm run mock` (see vite.config.js).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { buildFarm, DAY, FIXTURES, HOUR, iso, jobTotals } from "./data.js";

const PREFIX = "/mock-api";
const nowUnix = () => Math.floor(Date.now() / 1000);

class HttpError extends Error {
  constructor(status, detail, extra = {}) {
    super(detail);
    this.status = status;
    this.extra = extra;
  }
}
const notInMockup = (what) => new HttpError(501, `${what} isn't available in the mockup: it needs the real Farmhand backend.`);

export function mockApi() {
  let farm = buildFarm();
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
    has_prusalink_password: !!p.prusalink?.hasPassword,
  });
  const modelOut = (m) => ({
    id: m.id, name: m.name, file_type: m.file_type, created_at: m.created_at, notes: m.notes, notes_revision: m.notes_revision,
    notes_updated_at: m.notes_updated_at,
    versions: m.versions.map((v) => ({ id: v.id, version: v.version, file_path: v.file_path, thumbnail_path: v.thumbnail_path, note: v.note, uploaded_at: v.uploaded_at })),
  });
  const versionOut = (v) => {
    const { thumb, ...rest } = v;
    return rest;
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

  // ------------------------------------------------------------------ the farm
  on("GET", "/printers", () => [...farm.printers].sort((a, b) => a.name.localeCompare(b.name)).map(printerOut));
  on("GET", "/printers/:id", ({ id }) => printerOut(printer(id)));
  on("POST", "/printers", (_, body) => {
    if (!body.name?.trim()) throw new HttpError(422, "A printer needs a name");
    if (farm.printers.some((p) => p.name === body.name.trim())) throw new HttpError(409, `A printer named '${body.name}' already exists — name is the unique key, not IP`);
    const p = { id: farm.nextIds.printer++, name: body.name.trim(), kind: body.kind, wired_ip: body.wired_ip, wireless_ip: body.wireless_ip, decommissioned: false, created_at: iso(nowUnix()), moonraker: null, notes: "", serviceHoursSince: null, serviceHistory: [] };
    if (body.connection_type === "prusalink") {
      p.prusalink = { reachable: true, firmware: "6.2.0", username: body.prusalink_username || "maker", hasPassword: !!body.prusalink_password, url: body.prusalink_url || null };
    } else {
      p.moonraker_url_override = body.moonraker_url || null;
      p.apiKey = body.moonraker_api_key || null;
    }
    farm.printers.push(p);
    return [201, printerOut(p)];
  });
  on("PATCH", "/printers/:id", ({ id }, body) => {
    const p = printer(id);
    for (const k of ["name", "kind", "wired_ip", "wireless_ip", "decommissioned"]) if (k in body && body[k] !== undefined) p[k] = body[k];
    if ("moonraker_url" in body) p.moonraker_url_override = body.moonraker_url || null;
    if (body.moonraker_api_key != null) p.apiKey = body.moonraker_api_key || null;
    if (body.connection_type === "moonraker") delete p.prusalink;
    if (body.connection_type === "prusalink" && !p.prusalink) p.prusalink = { reachable: true, firmware: "6.2.0", username: "maker", hasPassword: false, url: null };
    if (p.prusalink) {
      if ("prusalink_url" in body) p.prusalink.url = body.prusalink_url || null;
      if (body.prusalink_username != null) p.prusalink.username = body.prusalink_username.trim() || "maker";
      if (body.prusalink_password != null) p.prusalink.hasPassword = !!body.prusalink_password;
    }
    return printerOut(p);
  });
  on("PUT", "/printers/:id/notes", ({ id }, body) => {
    const p = printer(id);
    saveNotes(p, body, { text: "notes", rev: "notesRevision", at: "notesUpdatedAt" });
    return printerOut(p);
  });
  on("GET", "/printers/:id/bundles", ({ id }) => farm.bundles.filter((b) => b.printer_id === Number(id)).map(bundleOut));

  on("GET", "/source-models", () => farm.models.map(modelOut));
  on("GET", "/source-models/:id", ({ id }) => modelOut(model(id)));
  // Renaming follows the real rules (backend/app/names.py): only the part before the extension changes, it's
  // tidied, and characters a file name can't have are refused
  const cleanName = (raw, extension) => {
    let stem = String(raw ?? "").split(/\s+/).filter(Boolean).join(" ");
    if (stem.toLowerCase().endsWith(extension.toLowerCase())) stem = stem.slice(0, -extension.length);
    stem = stem.replace(/[ .]+$/, "");
    if (!stem) throw new HttpError(422, "The name can't be empty");
    const bad = [...new Set([...stem].filter((ch) => '/\\:*?"<>|'.includes(ch) || ch.charCodeAt(0) < 32))].sort();
    if (bad.length) throw new HttpError(422, `A file name can't contain ${bad.join(" ")}`);
    const name = stem + extension;
    if (name.length > 255) throw new HttpError(422, "The name can be at most 255 characters");
    return name;
  };
  const extensionOf = (name, fallback) => (/\.[^./\\]+$/.exec(name) || [fallback])[0];
  on("PATCH", "/source-models/:id", ({ id }, body) => {
    const m = model(id);
    m.name = cleanName(body.name, extensionOf(m.name, { STL: ".stl", OBJ: ".obj", STEP: ".step" }[m.file_type] || ".stl"));
    return modelOut(m);
  });
  on("PATCH", "/bundles/versions/:id", ({ id }, body) => {
    const { v } = version(id);
    v.filename = cleanName(body.filename, ".3mf");
    return versionDetail(v);
  });
  on("PUT", "/source-models/:id/notes", ({ id }, body) => {
    const m = model(id);
    saveNotes(m, body);
    return modelOut(m);
  });
  on("DELETE", "/source-models/:id", ({ id }, _b, q) => {
    const m = model(id);
    const used = farm.bundles.filter((b) => b.source_model_ids.includes(m.id));
    if (used.length && q.get("cascade") !== "true") throw new HttpError(409, `${used.length} 3MF file(s) were sliced from this model — pass cascade=true to delete them too`);
    farm.bundles = farm.bundles.filter((b) => !b.source_model_ids.includes(m.id));
    farm.models = farm.models.filter((x) => x.id !== m.id);
    return [204, null];
  });
  on("DELETE", "/source-models/:id/versions/:v", ({ id, v }) => {
    const m = model(id);
    m.versions = m.versions.filter((x) => x.version !== Number(v));
    return [204, null];
  });
  on("POST", "/source-models/:id/versions/:v/thumbnail", () => ({ updated: true }));
  on("POST", "/source-models", () => { throw notInMockup("Uploading model files"); });
  on("POST", "/source-models/:id/versions", () => { throw notInMockup("Uploading model files"); });
  on("POST", "/source-models/scan", () => ({
    root: farm.storage.stl, truncated: false,
    files: [
      { path: `${farm.storage.stl}/new/Planter_v3.stl`, name: "Planter_v3.stl", folder: "new", size_bytes: 1834221, file_type: "STL", name_in_library: false },
      { path: `${farm.storage.stl}/Calibration cube.stl`, name: "Calibration cube.stl", folder: "", size_bytes: 68400, file_type: "STL", name_in_library: true },
    ],
  }));
  on("POST", "/source-models/scan/import", (_, body) => ({
    results: (body.paths || []).map((path) => {
      const name = path.split("/").pop();
      const m = { id: farm.nextIds.model++, name, file_type: "STL", created_at: iso(nowUnix()), versions: [{ id: 900 + farm.nextIds.model, version: 1, file_path: path, thumbnail_path: null, thumb: null, note: null, uploaded_at: iso(nowUnix()) }], notes: "", notes_revision: 0, notes_updated_at: null };
      farm.models.push(m);
      return { path, ok: true, error: null, source_model_id: m.id };
    }),
  }));

  on("GET", "/bundles", () => farm.bundles.map(bundleOut));
  on("GET", "/bundles/:id", ({ id }) => bundleOut(bundle(id)));
  on("POST", "/bundles", () => { throw notInMockup("Uploading 3MF files"); });
  on("POST", "/bundles/inspect", () => { throw notInMockup("Reading an uploaded 3MF"); });
  on("POST", "/bundles/:id/versions", () => { throw notInMockup("Uploading 3MF files"); });
  on("PUT", "/bundles/:id/notes", ({ id }, body) => {
    const b = bundle(id);
    saveNotes(b, body);
    return bundleOut(b);
  });
  on("PUT", "/bundles/:id/star", ({ id }, body) => {
    const b = bundle(id);
    if (body.version_id == null) b.starred_version_id = null;
    else {
      const v = b.versions.find((x) => x.id === Number(body.version_id));
      if (!v) throw new HttpError(422, `Version ${body.version_id} isn't a version of this 3MF`);
      if (v.version === 1) throw new HttpError(422, "The initial version can't be starred");
      b.starred_version_id = v.id;
    }
    return bundleOut(b);
  });
  on("GET", "/bundles/versions/:id", ({ id }) => versionDetail(version(id).v));
  // A version's G-code: uploading one (named after its 3MF, replacing one it had), and sending it to its printer
  on("PUT", "/bundles/versions/:id/gcode", ({ id }, body) => {
    const { b, v } = version(id);
    const name = body.files?.[0] || "";
    const ext = (/\.(bgcode|gcode)$/i.exec(name) || [])[0];
    if (!ext) throw new HttpError(422, "Pick a sliced .gcode or .bgcode file");
    if (!v.full_files_retained) throw new HttpError(422, "This version's files were pruned, so it can't be given a G-code any more");
    v.gcode_name = v.filename.replace(/\.3mf$/i, "") + ext.toLowerCase();
    return bundleOut(b);
  });
  on("POST", "/bundles/versions/:id/print", ({ id }) => {
    const { b, v } = version(id);
    if (!v.gcode_name) throw new HttpError(422, "This version has no G-code to send. Upload one first.");
    const p = printer(b.printer_id);
    if (p.prusalink) {
      if (liveJob(p)) throw new HttpError(409, `${p.name} isn't ready for a new print (it says PRINTING).`);
      p.prusalink.finished = null;
      (farm.jobs[p.id] ??= []).push({
        job_id: `${42 + farm.jobs[p.id].length}@mock`, filename: v.gcode_name, status: "in_progress", start: nowUnix(), printS: 0, totalS: 0,
        filamentMm: 0, kwh: null, avgW: null, maxW: null, estimated: 2.5 * HOUR,
      });
      return { sent: `usb/${v.gcode_name}`, printer: p.name };
    }
    if (/\.bgcode$/i.test(v.gcode_name)) throw new HttpError(422, `${p.name} runs Klipper, which can't print a .bgcode (Prusa's binary G-code). Slice a plain .gcode for it.`);
    if (!p.moonraker) throw new HttpError(502, "This printer has no IP address or Moonraker address set.", { kind: "no_address" });
    if (!p.moonraker.reachable) throw new HttpError(502, p.moonraker.error, { kind: p.moonraker.error_kind });
    if ((farm.jobs[p.id] || []).some((j) => j.status === "in_progress")) throw new HttpError(409, `${p.name} is printing, so a new print can't be started.`);
    return { sent: `gcodes/${v.gcode_name}`, printer: p.name };
  });
  on("PATCH", "/bundles/versions/:id/monument", ({ id }, body) => {
    const { v } = version(id);
    if (body.monument) {
      if (!body.note) throw new HttpError(422, "Monumenting a version requires a note explaining why it matters");
      Object.assign(v, { monument: true, monument_note: body.note });
    } else {
      if (!body.confirm) throw new HttpError(422, "Un-monumenting re-exposes this version to pruning — pass confirm=True to proceed");
      v.monument = false;
    }
    return versionDetail(v);
  });
  on("DELETE", "/bundles/versions/:id", ({ id }) => {
    const { b, v } = version(id);
    b.versions = b.versions.filter((x) => x.id !== v.id);
    if (b.starred_version_id === v.id) b.starred_version_id = null;
    if (!b.versions.length) farm.bundles = farm.bundles.filter((x) => x.id !== b.id);
    return [204, null];
  });
  on("DELETE", "/bundles/:id", ({ id }) => {
    farm.bundles = farm.bundles.filter((b) => b.id !== Number(id));
    return [204, null];
  });

  // ------------------------------------------------------------------ Moonraker: connection, history, energy, maintenance
  const reach = (p) => {
    if (p.prusalink) return; // its maintenance is kept in Farmhand: always there
    if (!p.moonraker) throw new HttpError(502, "This printer has no IP address or Moonraker address set.", { kind: "no_address" });
    if (!p.moonraker.reachable) throw new HttpError(502, p.moonraker.error, { kind: p.moonraker.error_kind });
  };
  const syncState = (p) => ({ last_sync_at: synced(p).last_sync_at ?? null, last_sync_error: synced(p).last_sync_error ?? null, totals: syncedTotals(p) });
  on("GET", "/printers/:id/moonraker", ({ id }) => {
    const p = printer(id);
    const out = { moonraker_url: moonrakerUrl(p), mainsail_url: mainsailUrl(p), has_api_key: !!p.apiKey, reachable: false, klippy_state: null, moonraker_version: null, error: null, error_kind: null, ...syncState(p) };
    if (!p.moonraker) return { ...out, error: "This printer has no IP address or Moonraker address set.", error_kind: "no_address" };
    if (!p.moonraker.reachable) return { ...out, error: p.moonraker.error, error_kind: p.moonraker.error_kind };
    // A job still in progress is the print running now; it carries on from where the sample data left it
    const job = (farm.jobs[p.id] || []).find((j) => j.status === "in_progress");
    const printed = job && Math.min(job.estimated - 60, job.printS + (nowUnix() - (job.seenFrom ??= nowUnix())));
    const print = job && {
      state: "printing", file: job.filename, progress: Math.round((printed / job.estimated) * 1000) / 10, print_duration: printed,
      time_remaining: job.estimated - printed, extruder: { temperature: 239.8, target: 240 }, heater_bed: { temperature: 100.2, target: 100 },
    };
    return { ...out, reachable: true, klippy_state: p.moonraker.klippy_state, moonraker_version: p.moonraker.version, print: print || null };
  });
  on("POST", "/printers/:id/moonraker/sync", ({ id }) => {
    const p = printer(id);
    try {
      reach(p);
    } catch (e) {
      farm.connections[p.id] = { ...synced(p), last_sync_error: e.message };
      throw e;
    }
    farm.connections[p.id] = { last_sync_at: iso(nowUnix()), last_sync_error: null };
    return { added: 0, updated: 0, ...syncState(p) };
  });
  const jobOut = (j, i) => ({
    id: i + 1, job_id: j.job_id, filename: j.filename, status: j.status, start_time: iso(j.start),
    end_time: j.status === "in_progress" ? null : iso(j.start + j.totalS), print_duration: j.printS, total_duration: j.totalS,
    filament_used: j.filamentMm, slicer: "PrusaSlicer", estimated_time: j.estimated, layer_height: 0.2, filament_type: "PLA",
    energy_kwh: j.kwh, avg_power_w: j.avgW, max_power_w: j.maxW,
  });
  on("GET", "/printers/:id/print-jobs", ({ id }, _b, q) => {
    const p = printer(id);
    let list = (farm.jobs[p.id] || []).map(jobOut).reverse(); // newest first
    const status = q.get("status");
    if (status === "failed") list = list.filter((j) => j.status !== "completed" && j.status !== "in_progress");
    else if (status) list = list.filter((j) => j.status === status);
    for (const w of (q.get("q") || "").toLowerCase().split(/\s+/).filter(Boolean)) list = list.filter((j) => j.filename.toLowerCase().includes(w));
    const limit = Number(q.get("limit") || 25);
    const offset = Number(q.get("offset") || 0);
    return { total: list.length, jobs: list.slice(offset, offset + limit) };
  });
  on("GET", "/printers/:id/print-stats", ({ id }) => {
    const p = printer(id);
    const t = totalsFor(p);
    const by = {};
    (farm.jobs[p.id] || []).forEach((j) => (by[j.status] = (by[j.status] || 0) + 1));
    return { ...syncState(p), archive: { jobs: t.total_jobs, by_status: by, print_time: t.total_print_time, filament_used: t.total_filament_used } };
  });
  on("GET", "/printers/:id/energy", ({ id }) => {
    const p = printer(id);
    const withEnergy = (farm.jobs[p.id] || []).filter((j) => j.kwh != null);
    const readings = farm.meterReadings[p.id] || [];
    const last = readings[readings.length - 1];
    return {
      meter: last ? { sensor: p.moonraker.meterSensor, energy_kwh: last[1], taken_at: iso(last[0]), first_reading_at: iso(readings[0][0]) } : null,
      print_total_kwh: withEnergy.length ? withEnergy.reduce((s, j) => s + j.kwh, 0) : null,
      jobs: withEnergy.map((j) => [iso(j.start), j.kwh]),
      readings: readings.map(([t, k]) => [iso(t), k]),
    };
  });

  // The 1500-hour service, kept in Farmhand
  const servicedPrinter = (id) => {
    const p = printer(id);
    if (p.serviceHoursSince == null) throw new HttpError(422, "The service count starts once the printer has been synced at least once");
    return p;
  };
  on("POST", "/printers/:id/service/done", ({ id }, body) => {
    const p = servicedPrinter(id);
    p.serviceHistory = [...(p.serviceHistory || []), { hoursAgoDays: 0, doneAt: nowUnix(), hours: Math.round(p.serviceHoursSince * 10) / 10, note: (body.note || "").trim() || null }];
    p.serviceHoursSince = 0;
    return printerOut(p);
  });
  on("PATCH", "/printers/:id/service", ({ id }, body) => {
    const p = servicedPrinter(id);
    p.serviceEnabled = !!body.enabled;
    return printerOut(p);
  });
  on("PUT", "/printers/:id/service/notes", ({ id }, body) => {
    const p = printer(id);
    saveNotes(p, body, { text: "serviceNotes", rev: "serviceNotesRevision", at: "serviceNotesUpdatedAt" });
    return printerOut(p);
  });

  // Maintenance kept on the printer, Mainsail's way: due once any enabled threshold is reached
  const maintenanceList = (p) => {
    reach(p);
    const totals = totalsFor(p);
    const now = nowUnix();
    const entries = Object.entries(farm.maintenance[p.id] || {}).map(([key, e]) => {
      const r = e.reminder || { type: null };
      let state = e.end_time != null ? "done" : r.type == null ? "no_reminder" : "ok";
      const checks = [];
      if (state === "ok") {
        if (r.filament?.bool) { const used = (totals.total_filament_used - e.start_filament) / 1000; checks.push({ kind: "filament", used, limit: r.filament.value, unit: "m", due: used >= r.filament.value }); }
        if (r.printtime?.bool) { const used = (totals.total_print_time - e.start_printtime) / HOUR; checks.push({ kind: "printtime", used, limit: r.printtime.value, unit: "h", due: used >= r.printtime.value }); }
        if (r.date?.bool) { const used = (now - e.start_time) / DAY; checks.push({ kind: "date", used, limit: r.date.value, unit: "days", due: used >= r.date.value }); }
        if (checks.some((c) => c.due)) state = "due";
      }
      return { id: key, name: e.name, note: e.note || "", perform_note: e.perform_note, start_time: e.start_time, end_time: e.end_time, last_entry: e.last_entry, reminder: r, state, checks };
    });
    entries.sort((a, b) => (a.end_time != null) - (b.end_time != null) || (b.end_time || b.start_time) - (a.end_time || a.start_time));
    return { entries, totals };
  };
  const cleanReminder = (r) => {
    const out = { type: r?.type ?? null };
    for (const part of ["filament", "printtime", "date"]) {
      const on = !!r?.[part]?.bool;
      const value = Number(r?.[part]?.value);
      if (on && !(value > 0)) throw new HttpError(422, `The ${part === "printtime" ? "print time" : part === "date" ? "days" : part} reminder must be more than 0`);
      out[part] = { bool: on, value: on ? value : null };
    }
    if (out.type && !["filament", "printtime", "date"].some((k) => out[k].bool)) throw new HttpError(422, "Pick at least one of filament, print time or days for the reminder");
    return out;
  };
  const freshEntry = (p, name, note, reminder, lastEntry = null) => {
    const t = totalsFor(p);
    return { name, note, perform_note: null, start_time: nowUnix(), end_time: null, start_filament: t.total_filament_used, end_filament: null, start_printtime: t.total_print_time, end_printtime: null, last_entry: lastEntry, reminder };
  };
  const noFilament = (p, r) => {
    if (p.prusalink && r.filament.bool) throw new HttpError(422, "This printer doesn't report how much filament it uses: pick print time or days for the reminder");
    return r;
  };
  const reachablePrinter = (id) => {
    const p = printer(id);
    reach(p);
    return p;
  };
  const entryFor = (p, key) => farm.maintenance[p.id]?.[decodeURIComponent(key)] || fail404("That maintenance entry isn't on the printer any more. It may have been deleted in Mainsail.");
  on("GET", "/printers/:id/maintenance", ({ id }) => maintenanceList(printer(id)));
  on("POST", "/printers/:id/maintenance", ({ id }, body) => {
    const p = reachablePrinter(id);
    if (!body.name?.trim()) throw new HttpError(422, "Give the maintenance a name");
    const key = crypto.randomUUID();
    (farm.maintenance[p.id] ??= {})[key] = freshEntry(p, body.name.trim(), (body.note || "").trim(), noFilament(p, cleanReminder(body.reminder)));
    return [201, { id: key, ...maintenanceList(p) }];
  });
  on("PUT", "/printers/:id/maintenance/:key", ({ id, key }, body) => {
    const p = reachablePrinter(id);
    const e = entryFor(p, key);
    if (body.name != null) e.name = body.name.trim();
    if (body.note != null) e.note = body.note.trim();
    if (body.reminder) e.reminder = noFilament(p, cleanReminder(body.reminder));
    return maintenanceList(p);
  });
  on("POST", "/printers/:id/maintenance/:key/done", ({ id, key }, body) => {
    const p = reachablePrinter(id);
    const e = entryFor(p, key);
    if (e.end_time != null) throw new HttpError(422, "That maintenance has already been marked done");
    const t = totalsFor(p);
    Object.assign(e, { end_time: nowUnix(), end_filament: t.total_filament_used, end_printtime: t.total_print_time, perform_note: (body.note || "").trim() || null });
    let nextId = null;
    if (e.reminder?.type === "repeat") {
      nextId = crypto.randomUUID();
      farm.maintenance[p.id][nextId] = freshEntry(p, e.name, e.note, { ...e.reminder }, decodeURIComponent(key));
    }
    return { next_id: nextId, ...maintenanceList(p) };
  });
  on("DELETE", "/printers/:id/maintenance/:key", ({ id, key }, _b, q) => {
    const p = printer(id);
    if (q.get("confirm") !== "true") throw new HttpError(409, "Deleting is permanent (in Mainsail too) — pass confirm=true to proceed");
    reach(p);
    entryFor(p, key);
    delete farm.maintenance[p.id][decodeURIComponent(key)];
    return maintenanceList(p);
  });

  // ------------------------------------------------------------------ PrusaLink: live status and sending a print
  // The running job moves on with the clock and finishes once its estimate is up; the printer then shows FINISHED.
  const liveJob = (p) => {
    const job = (farm.jobs[p.id] || []).find((j) => j.status === "in_progress");
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
  const prusaPrinter = (id) => {
    const p = printer(id);
    if (!p.prusalink) throw new HttpError(409, "This printer isn't set up for PrusaLink");
    return p;
  };
  on("GET", "/printers/:id/prusalink", ({ id }) => {
    const p = prusaPrinter(id);
    const out = {
      prusalink_url: prusalinkUrl(p), has_password: !!p.prusalink.hasPassword, reachable: false, error: null, error_kind: null,
      state: null, printer_type: null, firmware: null, temps: null, job: null, ...syncState(p),
    };
    if (!prusalinkUrl(p)) return { ...out, error: "This printer has no IP address or PrusaLink address set.", error_kind: "no_address" };
    if (!p.prusalink.hasPassword) return { ...out, error: "PrusaLink refused the login. Check the username (usually maker) and the password shown on the printer under Settings > Network > PrusaLink.", error_kind: "unauthorized" };
    if (!p.prusalink.reachable) return { ...out, error: `PrusaLink at ${prusalinkUrl(p)} didn't answer in time. Is the printer on?`, error_kind: "unreachable" };
    const job = liveJob(p);
    farm.connections[p.id] = { last_sync_at: iso(nowUnix()), last_sync_error: null };
    const done = !job && p.prusalink.finished;
    return {
      ...out, ...syncState(p), reachable: true, printer_type: "COREONE", firmware: p.prusalink.firmware,
      state: job ? "PRINTING" : done ? "FINISHED" : "IDLE",
      temps: job ? { temp_nozzle: 239.6, target_nozzle: 240, temp_bed: 85.2, target_bed: 85 } : { temp_nozzle: 27.4, target_nozzle: 0, temp_bed: 26.1, target_bed: 0 },
      job: job
        ? { id: 41, state: "PRINTING", file: job.filename, progress: Math.round((job.printS / job.estimated) * 1000) / 10, time_printing: job.printS, time_remaining: job.estimated - job.printS }
        : done ? { id: 41, state: "FINISHED", file: done.filename, progress: 100, time_printing: done.printS, time_remaining: 0 } : null,
    };
  });
  on("POST", "/printers/:id/prusalink/print", ({ id }, body) => {
    const p = prusaPrinter(id);
    const name = body.files?.[0] || "";
    if (!/\.(bgcode|gcode)$/i.test(name)) throw new HttpError(422, "The printer can only print a sliced .bgcode or .gcode file. Slice the 3MF first.");
    if (liveJob(p)) throw new HttpError(409, "The printer isn't ready for a new print (it says PRINTING).");
    p.prusalink.finished = null;
    (farm.jobs[p.id] ??= []).push({
      job_id: `${42 + farm.jobs[p.id].length}@mock`, filename: name, status: "in_progress", start: nowUnix(), printS: 0, totalS: 0,
      filamentMm: 0, kwh: null, avgW: null, maxW: null, estimated: 2.5 * HOUR,
    });
    return { sent: `usb/${name}` };
  });

  // ------------------------------------------------------------------ settings, storage, shares
  const location = (path) => ({
    path, default_path: path.includes("models") ? "/data/storage/source_models" : "/data/storage/bundles", is_default: false,
    status: { exists: true, writable: true, marker_ok: true, ready: true, free_bytes: 2.1e12, total_bytes: 4e12, separate_volume: true },
  });
  const storageOut = () => ({ browse_root: "/data", stl: location(farm.storage.stl), threemf: location(farm.storage.threemf), outside: { stl: 0, threemf: 0 } });
  const configLocation = () => ({
    path: farm.settingsFolder, is_set: !!farm.settingsFolder,
    status: farm.settingsFolder ? { exists: true, writable: true, marker_ok: true, ready: true } : null,
    file: farm.settingsFolder ? { exists: true, modified_at: iso(nowUnix() - 300), size: 2841 } : null,
    last_write: { ok: true, error: null, at: iso(nowUnix() - 300) },
  });
  on("GET", "/settings/config", () => ({ config: farm.config, location: configLocation() }));
  on("PUT", "/settings/config", (_, body) => {
    if (body.appearance) farm.config.appearance = { ...farm.config.appearance, ...body.appearance };
    if (body.preferences) farm.config.preferences = { ...farm.config.preferences, ...body.preferences };
    return { config: farm.config, mirror: { ok: true, skipped: !farm.settingsFolder, path: farm.settingsFolder, error: null } };
  });
  on("GET", "/settings/config/location/inspect", (_, _b, q) => ({ path: q.get("path"), file_exists: false, file_valid: null, modified_at: null, summary: null, error: null }));
  on("PUT", "/settings/config/location", (_, body) => {
    farm.settingsFolder = body.path || null;
    return { saved: true, needs_choice: false, found: null, restored: null, location: configLocation() };
  });
  on("POST", "/settings/config/save-now", () => ({ ok: true, skipped: false, path: farm.settingsFolder, error: null }));
  on("POST", "/settings/config/restore", () => ({ restored: ["appearance", "display preferences"], shares_added: [], shares_kept: ["farm-nas"], needs_password: [], warnings: [], records: null }));

  on("GET", "/settings/storage", () => storageOut());
  on("PUT", "/settings/storage", (_, body) => {
    if ("stl_path" in body) farm.storage.stl = body.stl_path || "/data/storage/source_models";
    if ("threemf_path" in body) farm.storage.threemf = body.threemf_path || "/data/storage/bundles";
    return storageOut();
  });
  on("GET", "/settings/storage/browse", (_, _b, q) => {
    const path = q.get("path") || "/data";
    const tree = { "/data": ["nas", "storage"], "/data/nas": ["farm-nas"], "/data/nas/farm-nas": ["3mf", "farmhand-settings", "models"], "/data/storage": ["bundles", "source_models"] };
    const parent = path === "/data" ? null : path.split("/").slice(0, -1).join("/") || "/data";
    return { path, root: "/data", parent, entries: (tree[path] || []).map((name) => ({ name, path: `${path}/${name}`, is_mount: path === "/data/nas" })) };
  });
  on("POST", "/settings/storage/folders", () => { throw notInMockup("Making folders"); });
  on("POST", "/settings/storage/migrate", () => ({ moved_stl: 0, moved_threemf: 0, missing: [], failed: [] }));
  const capability = { ok: true, smb: true, nfs: true, message: null, smb_message: null, nfs_message: null };
  on("GET", "/settings/storage/shares", () => ({ shares: farm.shares, capability }));
  on("POST", "/settings/storage/shares", () => { throw notInMockup("Connecting a network share"); });
  on("PATCH", "/settings/storage/shares/:id", () => { throw notInMockup("Changing a network share"); });
  on("POST", "/settings/storage/shares/:id/connect", ({ id }) => farm.shares.find((s) => s.id === Number(id)) || fail404("Share not found"));
  on("DELETE", "/settings/storage/shares/:id", ({ id }) => {
    farm.shares = farm.shares.filter((s) => s.id !== Number(id));
    return [204, null];
  });

  // ------------------------------------------------------------------ files: preview images and downloads
  const png = (slug) => (slug ? readFileSync(join(FIXTURES, "thumbs", `${slug.startsWith("stl-") ? slug : `3mf-${slug}`}.png`)) : null);
  const fileRoutes = [
    [/^\/bundles\/versions\/(\d+)\/thumbnail$/, (m) => png(version(m[1]).v.thumb)],
    [/^\/source-models\/(\d+)\/versions\/(\d+)\/thumbnail$/, (m) => png(model(m[1]).versions.find((v) => v.version === Number(m[2]))?.thumb)],
  ];
  const downloadRoutes = [
    [/^\/bundles\/versions\/(\d+)\/download\/(3mf|gcode)$/, (m) => [version(m[1]).v.filename.replace(/\.3mf$/, m[2] === "gcode" ? ".gcode" : ".3mf")]],
    [/^\/source-models\/(\d+)\/versions\/(\d+)\/download$/, (m) => [model(m[1]).name]],
  ];

  // ------------------------------------------------------------------ the Vite plugin
  return {
    name: "farmhand-mock-api",
    configureServer(server) {
      server.middlewares.use(PREFIX, async (req, res) => {
        const url = new URL(req.url, "http://mock");
        const send = (status, body, type = "application/json") => {
          res.statusCode = status;
          res.setHeader("Cache-Control", "no-store");
          if (body == null) return res.end();
          res.setHeader("Content-Type", type);
          res.end(type === "application/json" ? JSON.stringify(body) : body);
        };
        try {
          if (req.method === "POST" && url.pathname === "/__reset") {
            farm = buildFarm(); // a fresh sample farm, e.g. after trying deletes
            return send(200, { reset: true });
          }
          if (req.method === "GET") {
            for (const [re, get] of fileRoutes) {
              const m = url.pathname.match(re);
              if (m) {
                const image = get(m);
                return image ? send(200, image, "image/png") : send(404, { detail: "No thumbnail for this version" });
              }
            }
            for (const [re, get] of downloadRoutes) {
              const m = url.pathname.match(re);
              if (m) {
                const [name] = get(m);
                res.setHeader("Content-Disposition", `attachment; filename="${name}"`);
                return send(200, `Farmhand mockup: a stand-in for ${name}. The real file comes from the real backend.\n`, "text/plain");
              }
            }
          }
          const chunks = [];
          for await (const chunk of req) chunks.push(chunk);
          const raw = Buffer.concat(chunks).toString("utf-8");
          let body = {};
          if (raw && (req.headers["content-type"] || "").includes("application/json")) body = JSON.parse(raw);
          // an upload: only the names of the files sent are kept (the mockup doesn't store files)
          if ((req.headers["content-type"] || "").includes("multipart/form-data")) body = { files: [...raw.matchAll(/filename="([^"]*)"/g)].map((m) => m[1]) };
          for (const r of routes) {
            if (r.method !== req.method) continue;
            const m = url.pathname.match(r.re);
            if (!m) continue;
            const params = Object.fromEntries(r.keys.map((k, i) => [k, m[i + 1]]));
            await new Promise((done) => setTimeout(done, 120 + Math.random() * 180)); // feels like a real network
            const out = await r.handler(params, body, url.searchParams);
            return Array.isArray(out) && typeof out[0] === "number" && out.length === 2 ? send(out[0], out[1]) : send(200, out);
          }
          return send(404, { detail: `The mockup doesn't know ${req.method} ${url.pathname}` });
        } catch (e) {
          if (e instanceof HttpError) return send(e.status, { detail: e.message, ...e.extra });
          console.error("[mock-api]", e);
          return send(500, { detail: `Mockup error: ${e.message}` });
        }
      });
      server.config.logger.info("  Farmhand mockup: sample data served at /mock-api (no backend needed)");
    },
  };
}
