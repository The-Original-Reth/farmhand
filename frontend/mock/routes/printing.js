// A printer's Moonraker or PrusaLink: connection, print history, cameras, energy, the Farm cost page, the save
// location, the 1500-hour service and maintenance.
import { priceForMonth } from "../../src/lib/energyPrice.js";
import { HttpError, NO_MOONRAKER, nowUnix } from "../core.js";
import { DAY, HOUR, iso } from "../data.js";

export function printingRoutes(ctx) {
  const { capability, fail404, farm, liveJob, mainsailUrl, moonrakerUrl, on, printer, printerOut, prusalinkUrl, reachMoonraker, requireConfirm, runningJob, saveNotes, synced, syncedTotals, totalsFor } = ctx;

  // ------------------------------------------------------------------ Moonraker: connection, history, energy, maintenance
  const reach = (p) => {
    if (p.prusalink) return; // its maintenance is kept in Farmhand: always there
    reachMoonraker(p);
  };
  const syncState = (p) => ({ last_sync_at: synced(p).last_sync_at ?? null, last_sync_error: synced(p).last_sync_error ?? null, totals: syncedTotals(p) });
  on("GET", "/printers/:id/moonraker", ({ id }) => {
    const p = printer(id);
    const out = { moonraker_url: moonrakerUrl(p), mainsail_url: mainsailUrl(p), has_api_key: !!p.apiKey, reachable: false, klippy_state: null, moonraker_version: null, error: null, error_kind: null, ...syncState(p) };
    if (!p.moonraker) return { ...out, error: NO_MOONRAKER, error_kind: "no_address" };
    if (!p.moonraker.reachable) return { ...out, error: p.moonraker.error, error_kind: p.moonraker.error_kind };
    // A job still in progress is the print running now; it carries on from where the sample data left it
    const job = runningJob(p);
    const printed = job && Math.min(job.estimated - 60, job.printS + (nowUnix() - (job.seenFrom ??= nowUnix())));
    const print = job && {
      state: "printing", file: job.filename, progress: Math.round((printed / job.estimated) * 1000) / 10, print_duration: printed,
      time_remaining: job.estimated - printed, extruder: { temperature: 239.8, target: 240 }, heater_bed: { temperature: 100.2, target: 100 },
    };
    return { ...out, reachable: true, klippy_state: p.moonraker.klippy_state, moonraker_version: p.moonraker.version, print: print || null };
  });
  // A sample camera for each Klipper printer that's on: a drawn picture standing in for its snapshot
  const cameraPicture = () => {
    const t = new Date().toLocaleTimeString();
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2b3036"/><stop offset="1" stop-color="#111418"/></linearGradient></defs><rect width="640" height="360" fill="url(#g)"/><rect x="170" y="250" width="300" height="20" fill="#3a3f45"/><rect x="290" y="70" width="60" height="40" fill="#555b62"/><rect x="312" y="110" width="16" height="22" fill="#e0a43c"/><rect x="240" y="200" width="160" height="50" rx="4" fill="#2f8f83"/><text x="624" y="342" text-anchor="end" font-family="monospace" font-size="16" fill="#9aa3ab">${t}</text></svg>`;
    return "data:image/svg+xml," + encodeURIComponent(svg);
  };
  on("GET", "/printers/:id/webcams", ({ id }) => {
    const p = printer(id);
    // a Buddy3D's camera plays through go2rtc on the real server; the mockup has none, so it shows the sample picture
    if (p.prusalink && p.cameraAddress) return { webcams: [{ name: "Camera", service: "mjpegstreamer-adaptive", mjpeg: false, stream_url: null, snapshot_url: cameraPicture(), flip_horizontal: false, flip_vertical: false, rotation: 0, aspect_ratio: "16:9", target_fps: 1 }], error: null, board: null };
    if (p.prusalink) return { webcams: [], error: "No camera address set. Add the Buddy3D camera's IP on the printer's Edit page", board: null };
    if (!p.moonraker) return { webcams: [], error: NO_MOONRAKER, board: null };
    if (!p.moonraker.reachable) return { webcams: [], error: p.moonraker.error, board: null };
    // the computer Klipper runs on: every other sample printer is a CM4
    const board = p.id % 2 ? { name: "Pi 4", model: "Raspberry Pi 4 Model B Rev 1.5", memory_gb: 4 } : { name: "CM4", model: "Raspberry Pi Compute Module 4 Rev 1.1", memory_gb: 2 };
    return { webcams: [{ name: "Bed", service: "mjpegstreamer-adaptive", mjpeg: false, stream_url: null, snapshot_url: cameraPicture(), flip_horizontal: false, flip_vertical: false, rotation: 0, aspect_ratio: "16:9", target_fps: 1 }], error: null, board };
  });
  // How far along the print running now is, for Monitor's cameras
  on("GET", "/printers/:id/progress", ({ id }) => {
    const p = printer(id);
    const nothing = { state: null, progress: null, file: null, error: null };
    if (p.prusalink) {
      const job = p.prusalink.reachable && p.prusalink.hasPassword ? liveJob(p) : null;
      return job ? { ...nothing, state: "printing", progress: Math.round((job.printS / job.estimated) * 1000) / 10, file: job.filename } : nothing;
    }
    if (!p.moonraker?.reachable) return { ...nothing, error: p.moonraker?.error || NO_MOONRAKER };
    const job = runningJob(p);
    if (!job) return nothing;
    const printed = Math.min(job.estimated - 60, job.printS + (nowUnix() - (job.seenFrom ??= nowUnix())));
    return { ...nothing, state: "printing", progress: Math.round((printed / job.estimated) * 1000) / 10, file: job.filename };
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
  // A print's filament cost, worked out as the real API does (services/filament_cost.py): the price read from its
  // G-code (farm.gcodeFilament), else its 3MF on the same printer
  // by name (exactly, else without "ver N", else the slicer's "<3MF name>-printer-filament", the longest that fits;
  // spaces and underscores alike), the newest version uploaded before it started, and that version's filament
  // diameter, density and price per kg
  const stemOf = (name) => (name || "").replace(/\\/g, "/").split("/").pop().replace(/\.[^.]*$/, "").trim().toLowerCase();
  const keyOf = (stem) => stem.replace(/[\s_]+/g, "_");
  const baseOf = (stem) => keyOf(stem.replace(/\s*\bver\s*\d+$/i, "").replace(/[ ._-]+$/, "") || stem);
  const firstNumber = (v) => {
    const n = parseFloat(String(v ?? "").replace(/;/g, ",").split(",")[0]);
    return Number.isFinite(n) && n > 0 ? n : null;
  };
  const priced = (mm, price, density, diameter, source) => {
    const grams = (mm * Math.PI * (diameter / 2) ** 2 * density) / 1000;
    return { cost: Math.round((grams / 1000) * price * 100) / 100, grams: Math.round(grams * 10) / 10, cost_per_kg: price, density, diameter, ...source };
  };
  const filamentCost = (printerId, j) => {
    if (!(j.filamentMm > 0)) return null;
    // the price read from the printed G-code first
    const read = (farm.gcodeFilament[printerId] || {})[j.filename];
    if (read) return priced(j.filamentMm, read[0], read[1], read[2], { source: "gcode", filename: j.filename, bundle_id: null, version_id: null, version: null });
    const stem = stemOf(j.filename);
    const all = farm.bundles.filter((b) => b.printer_id === printerId).flatMap((b) => b.versions.map((v) => ({ b, v })));
    let found = all.filter(({ v }) => keyOf(stemOf(v.filename)) === keyOf(stem));
    if (!found.length) found = all.filter(({ v }) => baseOf(stemOf(v.filename)) === baseOf(stem));
    if (!found.length) {
      const fits = all.map(({ v }) => baseOf(stemOf(v.filename))).filter((b) => baseOf(stem).startsWith(`${b}-`));
      const longest = fits.sort((x, y) => y.length - x.length)[0];
      found = longest ? all.filter(({ v }) => baseOf(stemOf(v.filename)) === longest) : [];
    }
    if (!found.length) return null;
    found.sort((x, y) => Date.parse(x.v.uploaded_at) - Date.parse(y.v.uploaded_at));
    const before = found.filter(({ v }) => Date.parse(v.uploaded_at) <= j.start * 1000);
    const { b, v } = before.length ? before[before.length - 1] : found[0];
    const s = farm.versionSettings[v.id] || {};
    const price = firstNumber(s.filament_cost), density = firstNumber(s.filament_density);
    if (price == null || density == null) return null;
    return priced(j.filamentMm, price, density, firstNumber(s.filament_diameter) ?? 1.75,
      { source: "3mf", filename: v.filename, bundle_id: b.id, version_id: v.id, version: v.version });
  };
  const kwhPrice = () => farm.config.preferences.energy_price_per_kwh ?? null; // the Power page's average cost now
  // the price per kWh for the month a print started in, as the server works it out
  const prices = () => ({
    current: kwhPrice(), history: farm.config.preferences.energy_price_history || [], months: farm.config.preferences.energy_price_months || {},
  });
  const monthOf = (unix) => {
    const d = new Date(unix * 1000);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  };
  const jobOut = (p) => (j, i) => {
    const cost = filamentCost(p.id, j);
    const energyPrice = priceForMonth(prices(), monthOf(j.start));
    const energyCost = j.kwh != null && energyPrice != null ? Math.round(j.kwh * energyPrice * 100) / 100 : null;
    return {
      id: i + 1, job_id: j.job_id, filename: j.filename, status: j.status, start_time: iso(j.start),
      end_time: j.status === "in_progress" ? null : iso(j.start + j.totalS), print_duration: j.printS, total_duration: j.totalS,
      filament_used: j.filamentMm, slicer: "PrusaSlicer", estimated_time: j.estimated, layer_height: 0.2, filament_type: "PLA",
      energy_kwh: j.kwh, avg_power_w: j.avgW, max_power_w: j.maxW,
      // as the server does: from the cost's grams, else the slicer's estimate (the mock's PLA at about 2.96 g a metre)
      filament_grams: cost ? cost.grams : j.filamentMm > 0 && !p.prusalink ? Math.round(j.filamentMm * 0.00296 * 10) / 10 : null,
      filament_cost: cost ? cost.cost : null, filament_cost_detail: cost,
      energy_price: energyPrice, energy_cost: energyCost,
      // as the server does: filament + energy; no filament cost (none or 0) = that; no energy cost = the filament's
      total_cost: !cost?.cost ? (cost ? cost.cost : null) : Math.round((cost.cost + (energyCost ?? 0)) * 100) / 100,
    };
  };
  on("GET", "/printers/:id/print-jobs", ({ id }, _b, q) => {
    const p = printer(id);
    let list = (farm.jobs[p.id] || []).map(jobOut(p)).reverse(); // newest first
    const status = q.get("status");
    if (status === "failed") list = list.filter((j) => j.status !== "completed" && j.status !== "in_progress");
    else if (status) list = list.filter((j) => j.status === status);
    for (const w of (q.get("q") || "").toLowerCase().split(/\s+/).filter(Boolean)) list = list.filter((j) => j.filename.toLowerCase().includes(w));
    const limit = Number(q.get("limit") || 25);
    const offset = Number(q.get("offset") || 0);
    return { total: list.length, energy_price_per_kwh: kwhPrice(), jobs: list.slice(offset, offset + limit) };
  });
  // The Farm cost page's filament, as the server adds it up: every print that used filament, in the month it started
  on("GET", "/farm-cost", () => ({
    printers: farm.printers.map((p) => {
      const months = {};
      (farm.jobs[p.id] || []).map(jobOut(p)).filter((j) => j.filament_used > 0).forEach((j) => {
        const key = monthOf(Date.parse(j.start_time) / 1000);
        const m = (months[key] ??= { key, prints: 0, grams: 0, filament_cost: 0, unweighed: 0, uncosted: 0 });
        m.prints += 1;
        if (j.filament_grams == null) m.unweighed += 1;
        else m.grams += j.filament_grams;
        if (j.filament_cost == null) m.uncosted += 1;
        else m.filament_cost += j.filament_cost;
      });
      const list = Object.values(months).map((m) => ({ ...m, grams: Math.round(m.grams * 10) / 10, filament_cost: Math.round(m.filament_cost * 100) / 100 }));
      return { printer_id: p.id, months: list.sort((a, b) => (a.key < b.key ? 1 : -1)) };
    }),
    // where the server keeps each month's record: the folder chosen in Settings, else "farm-cost" above the STL folder
    records: {
      folder: farm.farmCostFolder || FARM_COST_DEFAULT, problem: null,
      saved: ["farmhand - farm cost - oct 2026.csv", "farmhand - farm cost - sep 2026.csv"],
    },
  }));
  const FARM_COST_DEFAULT = "/data/nas/farm-nas/farm-cost";
  const farmCostLocation = () => ({
    path: farm.farmCostFolder || FARM_COST_DEFAULT, is_default: !farm.farmCostFolder, default_path: FARM_COST_DEFAULT,
    status: { exists: true, writable: true, marker_ok: true, ready: true },
  });
  on("GET", "/farm-cost/location", () => farmCostLocation());
  // The save location: one place on the NAS for everything, as the server sets it up (connecting to the share, and
  // using or making STL, 3MF, Projects, farm-cost, stream and farmhand-configs inside it). A password of "wrong" is refused, to
  // try the error.
  // the share the save location is on: the one whose server and share the address starts with
  const saveLocationShare = () => {
    const at = String(farm.saveLocation || "").replace(/^(smb|cifs):\/\//i, "//").toLowerCase();
    return (farm.shares || []).find((s) => at.startsWith(`//${s.server}/${s.share}`.toLowerCase())) || null;
  };
  const saveLocationOut = () => ({
    address: farm.saveLocation || null,
    share: saveLocationShare(),
    capability,
    folders: {
      stl: farm.storage.stl, threemf: farm.storage.threemf, project: farm.storage.project,
      farm_cost: farm.farmCostFolder || FARM_COST_DEFAULT, stream: farm.streamFolder || `${farm.storage.stl.replace(/\/[^/]+$/, "")}/stream`, config: farm.settingsFolder || null,
    },
  });
  on("GET", "/settings/storage/save-location", () => saveLocationOut());
  on("PUT", "/settings/storage/save-location", (_, body) => {
    const address = String(body.address || "").trim();
    const m = address.replace(/\\/g, "/").replace(/^(smb|cifs):\/\//i, "//").match(/^\/\/([^/]+)\/(.+?)\/*$/);
    if (!m) throw new HttpError(422, "Type the NAS address as //server/share (a folder inside it can follow: //server/share/Farmhand).");
    if (body.password === "wrong") {
      throw new HttpError(422, `The NAS turned the connection down (mount error 1). Check that the username (${body.username || "guest"}) and password are right and that user may use this share.`);
    }
    const base = `/data/nas/${m[2].split("/")[0].toLowerCase().replace(/[^a-z0-9._-]+/g, "-")}${m[2].includes("/") ? "/" + m[2].split("/").slice(1).join("/") : ""}`;
    farm.storage.stl = `${base}/STL`;
    farm.storage.threemf = `${base}/3MF`;
    farm.storage.project = `${base}/Projects`;
    farm.farmCostFolder = `${base}/farm-cost`;
    farm.streamFolder = `${base}/stream`;
    farm.settingsFolder = `${base}/farmhand-configs`;
    farm.saveLocation = address;
    let share = saveLocationShare();
    if (!share) {
      // a new place: its share is added, connected (as the server does)
      const shareName = m[2].split("/")[0];
      share = {
        id: Math.max(0, ...(farm.shares || []).map((s) => s.id)) + 1, name: shareName, protocol: "smb", server: m[1], share: m[2],
        username: body.username || null, domain: null, version: null, has_password: !!body.password, address: `smb://${m[1]}/${m[2]}`,
        mount_point: `/data/nas/${shareName.toLowerCase()}`, mounted: true, error: null, error_kind: null, files_here: 0,
      };
      farm.shares = [...(farm.shares || []), share];
    }
    if ("domain" in body) share.domain = body.domain || null;
    if ("version" in body) share.version = body.version || null;
    if (body.username !== undefined) share.username = body.username || null;
    return { ...saveLocationOut(), config_choice: null };
  });
  on("PUT", "/farm-cost/location", (_, body) => {
    farm.farmCostFolder = body.path && body.path.trim() ? body.path.trim() : null;
    return farmCostLocation();
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
    // totalled by month as the real server does (services/energy.py), in this machine's time zone (the browser's)
    const months = {};
    const month = (t) => {
      const key = monthOf(t);
      return (months[key] ??= { key, prints: 0, print_count: 0, whole: null, partial: false });
    };
    withEnergy.forEach((j) => {
      const m = month(j.start);
      m.prints += j.kwh;
      m.print_count += 1;
    });
    readings.forEach(([t, k], i) => {
      const m = month(t);
      if (i === 0) {
        m.partial = true;
        m.whole ??= 0;
      } else {
        const before = readings[i - 1][1];
        m.whole = (m.whole ?? 0) + (k >= before ? k - before : k);
      }
    });
    const jobsKwh = withEnergy.reduce((s, j) => s + j.kwh, 0);
    return {
      meter: last ? { sensor: p.moonraker.meterSensor, energy_kwh: last[1], taken_at: iso(last[0]), first_reading_at: iso(readings[0][0]) } : null,
      print_total_kwh: withEnergy.length ? jobsKwh : null,
      print_jobs_kwh: jobsKwh,
      months: Object.values(months).sort((a, b) => (a.key < b.key ? 1 : -1)),
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
      const enabled = !!r?.[part]?.bool;
      const value = Number(r?.[part]?.value);
      if (enabled && !(value > 0)) throw new HttpError(422, `The ${part === "printtime" ? "print time" : part === "date" ? "days" : part} reminder must be more than 0`);
      out[part] = { bool: enabled, value: enabled ? value : null };
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
    requireConfirm(q, "Deleting is permanent (in Mainsail too) — pass confirm=true to proceed");
    const p = printer(id);
    reach(p);
    entryFor(p, key);
    delete farm.maintenance[p.id][decodeURIComponent(key)];
    return maintenanceList(p);
  });

  // ------------------------------------------------------------------ PrusaLink: live status and sending a print
  const prusaPrinter = (id) => {
    const p = printer(id);
    if (!p.prusalink) throw new HttpError(409, "This printer isn't set up for PrusaLink");
    return p;
  };
  on("GET", "/printers/:id/prusalink/password", ({ id }) => {
    const p = prusaPrinter(id);
    return { password: p.prusalink.password || (p.prusalink.hasPassword ? "sample-password" : null) };
  });
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
  return { reach, syncState, cameraPicture, stemOf, keyOf, baseOf, firstNumber, priced, filamentCost, kwhPrice, prices, monthOf, jobOut, FARM_COST_DEFAULT, farmCostLocation, saveLocationShare, saveLocationOut, servicedPrinter, maintenanceList, cleanReminder, freshEntry, noFilament, reachablePrinter, entryFor, prusaPrinter };
}
