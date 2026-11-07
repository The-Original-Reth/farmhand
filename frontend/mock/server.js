// The mockup's backend: a Vite plugin that answers the web UI's API calls under /mock-api from the sample farm in
// data.js, in exactly the shapes the real FastAPI backend uses. Changes (notes, stars, maintenance...) are kept in
// memory until the mockup restarts. Things that need real files or hardware (STL uploads, scanning, NAS mounting)
// answer with a plain "not in the mockup" message; a 3MF upload is read from its file name (see readThreemf). Only loaded by `npm run mock` (see vite.config.js).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { buildFarm, DAY, DEFAULT_PARTS, defaultParts, FIXTURES, HOUR, iso, jobTotals } from "./data.js";
import { priceForMonth, withNewAverage } from "../src/lib/energyPrice.js";

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

  // ------------------------------------------------------------------ the farm
  // ------------------------------------------------------------------ projects: made, listed, renamed, deleted
  const project = (id) => farm.projects.find((p) => p.id === Number(id)) || fail404("Project not found");
  const projectName = (body, except) => {
    const name = String(body.name ?? "").split(/\s+/).filter(Boolean).join(" ");
    if (!name) throw new HttpError(409, "A project needs a name.");
    if (name.length > 200) throw new HttpError(409, "A project's name can be at most 200 characters.");
    const clash = farm.projects.find((p) => p !== except && p.name.toLowerCase() === name.toLowerCase());
    if (clash) throw new HttpError(409, `There's already a project called ${clash.name}.`);
    return name;
  };
  // As the API answers: a project's own files (CAD, STL) are named after their newest version; the stand-in preview
  // picture stays in the mockup
  const filesOut = (files) =>
    files.map((f) => ({
      id: f.id, name: f.versions[0].filename, created_at: f.created_at,
      ...("printer_id" in f ? { printer_id: f.printer_id } : {}),
      ...("need" in f ? { need: f.need, have: f.have, component: f.component || null } : {}),
      versions: f.versions.map(({ thumb, gcode, ...v }) => ({ ...v, has_preview: !!thumb, ...("printer_id" in f ? { gcode_name: gcode || null } : {}) })),
    }));
  const projectOut = (p) => ({
    id: p.id, name: p.name, created_at: p.created_at,
    doc_files: filesOut(p.doc_files || []), cad_files: filesOut(p.cad_files), stl_files: filesOut(p.stl_files), threemf_files: filesOut(p.threemf_files),
    source_model_ids: [...p.source_model_ids], bundle_ids: [...p.bundle_ids], printer_ids: [...p.printer_ids],
    source_models: p.source_model_ids.map((id) => ({
      id, need: p.model_counts?.[id]?.need ?? 1, have: p.model_counts?.[id]?.have ?? 0, component: p.model_counts?.[id]?.component || null,
    })),
    parts: p.parts.map((x) => ({ ...x })),
  });
  on("GET", "/projects", () => [...farm.projects].sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase())).map(projectOut));
  on("POST", "/projects", (_p, body) => {
    const p = {
      id: farm.nextIds.project++, name: projectName(body), created_at: iso(nowUnix()),
      doc_files: [], cad_files: [], stl_files: [], threemf_files: [], source_model_ids: [], bundle_ids: [], printer_ids: [], parts: [],
    };
    farm.projects.push(p);
    return [201, projectOut(p)];
  });
  // Scan projects (before /projects/:id). A sample folder of project folders on the NAS, as the real scan sees it:
  // each name -> its files, sorted into kinds the way the API sorts them.
  const SCAN_ROOT = "/data/nas/farm-nas/projects";
  const scanFolders = {
    "Aquarium shop order": ["Quote.pdf", "Stand.stl"],
    "Dragon egg": ["Egg shell.stl", "Stand/Base.stl", "Stand/Claw.stl", "Egg.step", "Egg plate.3mf", "Egg plate.gcode", "Paint notes.txt"],
    "Shark display": ["Body/Left/Gill.stl", "Fins/Dorsal fin.stl", "Fins/Tail.stl", "Stand.stl", "Order.pdf"],
  };
  const scanKind = (name) =>
    /\.(stl|obj)$/i.test(name) ? "stl" : /\.3mf$/i.test(name) ? "threemf" : /\.(gcode|bgcode)$/i.test(name) ? "gcode"
      : /\.(step|stp|iges|igs|brep|brp|f3d|f3z|sldprt|sldasm|scad|fcstd|ipt|iam|3dm|blend|skp|dwg|dxf)$/i.test(name) ? "cad" : "doc";
  const scanCounts = (files) => {
    const counts = { doc: 0, cad: 0, stl: 0, threemf: 0, gcode: 0 };
    for (const f of files) counts[scanKind(f)] += 1;
    return counts;
  };
  const scanFolder = (path) => {
    const at = String(path || "").replace(/\/+$/, "");
    if (!at.startsWith("/")) throw new HttpError(422, "Use a full path (starting with /).");
    if (!at.startsWith("/data")) throw new HttpError(422, "That folder isn't under /data. Only folders where network storage is mounted for Farmhand can be chosen.");
    if (at !== SCAN_ROOT) throw new HttpError(422, `In the mockup, only ${SCAN_ROOT} has project folders to scan.`);
    return at;
  };
  on("GET", "/projects/scan", (_p, _b, q) => {
    const path = scanFolder(q.get("path"));
    const taken = new Set(farm.projects.map((p) => p.name.toLowerCase()));
    return {
      path,
      folders: Object.entries(scanFolders).map(([name, files]) => {
        const counts = scanCounts(files);
        return { name, path: `${path}/${name}`, files: counts, total: files.length, in_farmhand: taken.has(name.toLowerCase()), error: null };
      }),
    };
  });
  on("POST", "/projects/import", (_p, body) => {
    const path = String(body.path || "");
    const name = path.split("/").pop();
    const files = scanFolders[name];
    if (scanFolder(path.split("/").slice(0, -1).join("/")) && !files) throw new HttpError(422, `${path} isn't a folder.`);
    if (farm.projects.some((p) => p.name.toLowerCase() === name.toLowerCase())) {
      throw new HttpError(409, `There's already a project called ${name}: it isn't brought in again.`);
    }
    const p = {
      id: farm.nextIds.project++, name, created_at: iso(nowUnix()),
      doc_files: [], cad_files: [], stl_files: [], threemf_files: [], source_model_ids: [], bundle_ids: [], printer_ids: [], parts: [],
    };
    const counts = { doc: 0, cad: 0, stl: 0, threemf: 0, gcode: 0 };
    const threemfs = {};
    for (const rel of files) {
      const kind = scanKind(rel);
      if (kind === "gcode") continue; // after the 3MFs
      const parts = rel.split("/");
      const f = { id: farm.nextIds.cad++, created_at: iso(nowUnix()), versions: [] };
      if (kind === "stl") Object.assign(f, { need: 1, have: 0, component: parts.slice(0, -1).join("/") || null });
      if (kind === "threemf") f.printer_id = null;
      addFileVersion(f, { files: [parts[parts.length - 1]], fields: {} });
      p[KIND[kind].list].push(f);
      if (kind === "threemf") threemfs[rel.replace(/\.3mf$/i, "").toLowerCase()] = f;
      counts[kind] += 1;
    }
    for (const rel of files.filter((x) => scanKind(x) === "gcode")) {
      const match = threemfs[rel.replace(/\.(gcode|bgcode)$/i, "").toLowerCase()];
      if (match) {
        match.versions[0].gcode = rel.split("/").pop();
        counts.gcode += 1;
      } else {
        const f = { id: farm.nextIds.cad++, created_at: iso(nowUnix()), versions: [] };
        addFileVersion(f, { files: [rel.split("/").pop()], fields: {} });
        p.doc_files.push(f);
        counts.doc += 1;
      }
    }
    farm.projects.push(p);
    return [201, { project_id: p.id, name, files: counts, warnings: [] }];
  });
  on("GET", "/projects/check", () => {
    // the mockup keeps no files, so it reports a sample: the first project's first document as missing, one stray file
    const kinds = ["doc_files", "cad_files", "stl_files", "threemf_files"];
    const checked = farm.projects.reduce((n, p) => n + kinds.reduce((m, k) => m + (p[k] || []).reduce((s, f) => s + f.versions.length, 0), 0), 0);
    const first = farm.projects.find((p) => (p.doc_files || []).length);
    const problems = first
      ? [{
          project_id: first.id, project: first.name, kind: "doc", file_id: first.doc_files[0].id, version: first.doc_files[0].versions[0].version,
          filename: first.doc_files[0].versions[0].filename, path: `/data/nas/farm-nas/projects/${first.id}/docs/${first.doc_files[0].id}/v1`, problem: "missing",
        }]
      : [];
    const unknown = ["/data/nas/farm-nas/projects/stray notes.txt"];
    return {
      projects: farm.projects.length, files_checked: checked, root: "/data/nas/farm-nas/projects", error: null,
      problems, problems_total: problems.length, unknown, unknown_total: unknown.length,
    };
  });
  on("GET", "/projects/:id", ({ id }) => projectOut(project(id)));
  on("PATCH", "/projects/:id", ({ id }, body) => {
    const p = project(id);
    p.name = projectName(body, p);
    return projectOut(p);
  });
  // models from the Models page: put in a project, or taken out (the model stays)
  on("PUT", "/projects/:id/source-models/:mid", ({ id, mid }) => {
    const p = project(id);
    const m = model(mid);
    if (!p.source_model_ids.includes(m.id)) p.source_model_ids.push(m.id);
    return projectOut(p);
  });
  on("DELETE", "/projects/:id/source-models/:mid", ({ id, mid }) => {
    const p = project(id);
    p.source_model_ids = p.source_model_ids.filter((x) => x !== Number(mid));
    if (p.model_counts) delete p.model_counts[mid]; // put back in later, it starts afresh (counts, sub-component)
    return projectOut(p);
  });
  // 3MFs from the rest of Farmhand (bringing their printer) and printers: put in a project, or taken out
  const linkPrinter = (p, printerId) => {
    if (!p.printer_ids.includes(printerId)) p.printer_ids.push(printerId);
  };
  on("PUT", "/projects/:id/bundles/:bid", ({ id, bid }) => {
    const p = project(id);
    const b = farm.bundles.find((x) => x.id === Number(bid)) || fail404("Bundle not found");
    if (!p.bundle_ids.includes(b.id)) p.bundle_ids.push(b.id);
    linkPrinter(p, b.printer_id);
    return projectOut(p);
  });
  on("DELETE", "/projects/:id/bundles/:bid", ({ id, bid }) => {
    const p = project(id);
    p.bundle_ids = p.bundle_ids.filter((x) => x !== Number(bid));
    return projectOut(p);
  });
  on("PUT", "/projects/:id/printers/:pid", ({ id, pid }) => {
    const p = project(id);
    const printer = farm.printers.find((x) => x.id === Number(pid)) || fail404("Printer not found");
    linkPrinter(p, printer.id);
    return projectOut(p);
  });
  on("DELETE", "/projects/:id/printers/:pid", ({ id, pid }) => {
    const p = project(id);
    p.printer_ids = p.printer_ids.filter((x) => x !== Number(pid));
    return projectOut(p);
  });
  // The BOM (parts list): parts one at a time, or a BOM CSV. As the API: a name, a quantity of 1 or more, an http(s)
  // link (https:// added when none is typed) and notes.
  // How many are needed (1 or more; blank 1) and had (0 or more; blank 0), as the API checks them
  const countFields = (body, partial = false) => {
    const out = {};
    for (const [key, least, what] of [["need", 1, "How many are needed"], ["have", 0, "How many you have"]]) {
      if (partial && body[key] == null) continue;
      const n = String(body[key] ?? "").trim() === "" ? least : Number(body[key]);
      if (!Number.isInteger(n) || n < least) throw new HttpError(422, `${what} must be a whole number from ${least}.`);
      out[key] = n;
    }
    return out;
  };
  // The sub-component an STL is in, as the API keeps it: "Body / Fins" or "Body\\Fins" is "Body/Fins"; blank is none
  const cleanComponent = (text) => {
    const name = String(text ?? "").replace(/\\/g, "/").split("/").map((x) => x.trim().split(/\s+/).join(" ")).filter(Boolean).join("/");
    if (name.length > 200) throw new HttpError(422, "A sub-component's name can be at most 200 characters.");
    return name || null;
  };
  const componentField = (body) => ("component" in body ? { component: cleanComponent(body.component) } : {});
  on("PATCH", "/projects/:id/source-models/:mid", ({ id, mid }, body) => {
    const p = project(id);
    if (!p.source_model_ids.includes(Number(mid))) fail404("That model isn't in this project");
    p.model_counts = p.model_counts || {};
    p.model_counts[mid] = { need: 1, have: 0, ...p.model_counts[mid], ...countFields(body, true), ...componentField(body) };
    return projectOut(p);
  });
  on("PATCH", "/projects/:id/stl/:fid", ({ id, fid }, body) => {
    const p = project(id);
    const f = p.stl_files.find((x) => x.id === Number(fid)) || fail404("STL file not found");
    Object.assign(f, countFields(body, true), componentField(body));
    return projectOut(p);
  });
  // a project 3MF version's G-code: the mockup keeps its name; Send says it went (no printer is reached)
  const projectGcodeVersion = (id, fid, v) => fileVersion(id, "threemf", fid, v);
  on("PUT", "/projects/:id/threemf/:fid/versions/:v/gcode", ({ id, fid, v }, body) => {
    const name = body.files?.[0] || "";
    if (!/\.b?gcode$/i.test(name)) throw new HttpError(422, "Pick a sliced .gcode or .bgcode file");
    projectGcodeVersion(id, fid, v).gcode = name;
    return projectOut(project(id));
  });
  on("POST", "/projects/:id/threemf/:fid/versions/:v/print", ({ id, fid, v }) => {
    const ver = projectGcodeVersion(id, fid, v);
    if (!ver.gcode) fail404("This version has no G-code. Upload one first.");
    const f = projectFile(id, "threemf", fid);
    const printer = farm.printers.find((x) => x.id === f.printer_id);
    if (!printer) throw new HttpError(422, "This 3MF has no printer to send it to.");
    return { sent: `gcodes/${ver.gcode}`, printer: printer.name };
  });
  const bomPartFields = (body, partial = false) => {
    const out = {};
    if (!partial || "name" in body) {
      out.name = String(body.name ?? "").split(/\s+/).filter(Boolean).join(" ");
      if (!out.name) throw new HttpError(422, "A part needs a name.");
    }
    Object.assign(out, countFields(body, partial));
    if (!partial || "link" in body) {
      let link = String(body.link ?? "").trim();
      if (link && !/^[A-Za-z][A-Za-z0-9+.-]*:(?!\d)/.test(link)) link = `https://${link}`;
      if (link && !/^https?:\/\/[^\s/]+/i.test(link)) throw new HttpError(422, "The link must be a web address, like https://www.amazon.com/...");
      out.link = link || null;
    }
    if (!partial || "note" in body) out.note = String(body.note ?? "").trim() || null;
    return out;
  };
  on("POST", "/projects/:id/parts/bom", ({ id }, body) => {
    // the mockup only sees the file's name, not what's in it: it adds two sample parts as a stand-in
    const p = project(id);
    if (!/\.csv$/i.test(body.files?.[0] || "")) throw new HttpError(422, "That BOM is empty: the template has the columns to fill in.");
    if (body.fields?.replace === "true") p.parts = [];
    const added = [
      { name: "M3x8 screw (from the BOM)", need: 32, have: 0, link: "https://www.boltdepot.com/", note: "Mockup: a stand-in for the CSV's rows" },
      { name: "Rubber foot (from the BOM)", need: 8, have: 8, link: null, note: null },
    ];
    for (const part of added) p.parts.push({ id: farm.nextIds.part++, ...part });
    return { project: projectOut(p), added: added.length };
  });
  on("POST", "/projects/:id/parts", ({ id }, body) => {
    const p = project(id);
    p.parts.push({ id: farm.nextIds.part++, ...bomPartFields(body) });
    return [201, projectOut(p)];
  });
  on("PATCH", "/projects/:id/parts/:partId", ({ id, partId }, body) => {
    const p = project(id);
    const part = p.parts.find((x) => x.id === Number(partId)) || fail404("Part not found");
    Object.assign(part, bomPartFields(body, true));
    return projectOut(p);
  });
  on("DELETE", "/projects/:id/parts/:partId", ({ id, partId }, _b, q) => {
    requireConfirm(q);
    const p = project(id);
    p.parts = p.parts.filter((x) => x.id !== Number(partId));
    return projectOut(p);
  });
  // A project's own files, CAD, STL or 3MF: the mockup keeps their names and sizes, not the files ("Bracket.f3d" as version
  // 2 is "Bracket ver 2.f3d"). A kind the real backend draws a preview of gets a stand-in picture here.
  const withVersion = (name, n) => {
    const dot = name.lastIndexOf(".");
    const [stem, ext] = dot > 0 ? [name.slice(0, dot), name.slice(dot)] : [name, ""];
    return `${stem.replace(/\s*\bver\s*\d+$/i, "").replace(/[ ._-]+$/, "") || stem} ver ${n}${ext}`;
  };
  const previewable = (name) => /\.(stl|obj|step|stp|iges|igs|brep|f3d|f3z|3mf|png|jpe?g|gif|webp|bmp)$/i.test(name);
  const KIND = {
    doc: { list: "doc_files", noun: "document" },
    cad: { list: "cad_files", noun: "CAD file" }, stl: { list: "stl_files", noun: "STL file" }, threemf: { list: "threemf_files", noun: "3MF file" },
  };
  const kindOf = (kind) => KIND[kind] || fail404("Not found");
  const projectFile = (id, kind, fid) =>
    project(id)[kindOf(kind).list].find((f) => f.id === Number(fid)) || fail404(`${kindOf(kind).noun} not found`);
  const fileVersion = (id, kind, fid, v) =>
    projectFile(id, kind, fid).versions.find((x) => x.version === Number(v)) || fail404(`${kindOf(kind).noun} version not found`);
  const isStl = (name) => /\.(stl|obj)$/i.test(name || "");
  const addFileVersion = (f, body) => {
    const n = (f.versions[0]?.version || 0) + 1;
    const filename = withVersion(body.files?.[0] || "File", n);
    f.versions.unshift({
      version: n, filename, size_bytes: 1_250_000, note: String(body.fields?.note || "").trim() || null, uploaded_at: iso(nowUnix()),
      thumb: !previewable(filename) ? null : /\.3mf$/i.test(filename) ? "frog-vt1190" : "stl-frog-keychain",
    });
  };
  on("POST", "/projects/:id/:kind", ({ id, kind }, body) => {
    const p = project(id);
    kindOf(kind);
    const name = body.files?.[0] || "";
    let component = null; // an STL's sub-component
    if (kind === "stl") {
      if (!isStl(name)) throw new HttpError(422, "An STL file has to be an .stl or .obj file.");
      if (body.fields?.in_models === undefined) throw new HttpError(422, "Say whether it also goes in Models (in_models).");
      component = cleanComponent(body.fields?.component); // the folder it came from
      if (body.fields.in_models === "true") {
        // a new model in Models (as the real one, kept in the STL folder), which the project then uses
        const m = {
          id: farm.nextIds.model++, name, file_type: /\.obj$/i.test(name) ? "OBJ" : "STL", created_at: iso(nowUnix()),
          versions: [{ id: 900 + farm.nextIds.model, version: 1, file_path: `${farm.storage.stl}/${farm.nextIds.model}/v1/${name}`, thumbnail_path: "x", thumb: "stl-frog-keychain", note: String(body.fields?.note || "").trim() || null, uploaded_at: iso(nowUnix()) }],
          notes: "", notes_revision: 0, notes_updated_at: null,
        };
        farm.models.push(m);
        p.source_model_ids.push(m.id);
        if (component) {
          p.model_counts = p.model_counts || {};
          p.model_counts[m.id] = { need: 1, have: 0, component };
        }
        return [201, projectOut(p)];
      }
    }
    if (kind === "threemf" && !/\.3mf$/i.test(name)) throw new HttpError(422, "A 3MF file has to be a .3mf file.");
    const f = { id: farm.nextIds.cad++, created_at: iso(nowUnix()), versions: [], ...(kind === "stl" ? { need: 1, have: 0, component } : {}) };
    if (kind === "threemf") {
      // the printer it's for comes into the project too
      const pid = body.fields?.printer_id ? Number(body.fields.printer_id) : null;
      if (pid != null && !farm.printers.some((x) => x.id === pid)) fail404("Printer not found");
      f.printer_id = pid;
      if (pid != null) linkPrinter(p, pid);
    }
    addFileVersion(f, body);
    p[KIND[kind].list].push(f);
    return [201, projectOut(p)];
  });
  on("POST", "/projects/:id/:kind/:fid/versions", ({ id, kind, fid }, body) => {
    if (kind === "stl" && !isStl(body.files?.[0])) throw new HttpError(422, "An STL file has to be an .stl or .obj file.");
    addFileVersion(projectFile(id, kind, fid), body);
    return [201, projectOut(project(id))];
  });
  on("DELETE", "/projects/:id/:kind/:fid/versions/:v", ({ id, kind, fid, v }, _b, q) => {
    requireConfirm(q);
    const p = project(id);
    const f = projectFile(id, kind, fid);
    const ver = fileVersion(id, kind, fid, v);
    f.versions = f.versions.filter((x) => x !== ver);
    if (!f.versions.length) p[KIND[kind].list] = p[KIND[kind].list].filter((x) => x !== f);
    return projectOut(p);
  });
  // a project's documents or CAD files, put in this order: every one of them, first to last
  on("PUT", "/projects/:id/:kind/order", ({ id, kind }, body) => {
    if (kind !== "doc" && kind !== "cad") fail404("Not found");
    const p = project(id);
    const list = p[KIND[kind].list] || [];
    const ids = (body.ids || []).map(Number);
    if (ids.length !== list.length || new Set(ids).size !== ids.length || !ids.every((i) => list.some((f) => f.id === i))) {
      throw new HttpError(422, `The list of ${KIND[kind].noun}s has changed since it was shown: reload the page and arrange them again.`);
    }
    p[KIND[kind].list] = ids.map((i) => list.find((f) => f.id === i));
    return projectOut(p);
  });
  on("DELETE", "/projects/:id/:kind/:fid", ({ id, kind, fid }, _b, q) => {
    requireConfirm(q);
    const p = project(id);
    const f = projectFile(id, kind, fid);
    p[KIND[kind].list] = p[KIND[kind].list].filter((x) => x !== f);
    return projectOut(p);
  });
  on("DELETE", "/projects/:id", ({ id }, _b, q) => {
    requireConfirm(q);
    const p = project(id);
    farm.projects = farm.projects.filter((x) => x !== p);
    return [204, null];
  });

  on("GET", "/printers", () => [...farm.printers].sort((a, b) => a.name.localeCompare(b.name)).map(printerOut));
  // The range a scan starts with: as the real API in Docker, the /24 most of the farm's printers are on
  on("GET", "/printers/discover/range", () => {
    const count = {};
    for (const ip of farm.printers.flatMap((p) => [p.wired_ip, p.wireless_ip])) {
      const m = /^(10|172|192)\.(\d+)\.(\d+)\.\d+$/.exec(ip || "");
      if (m) count[`${m[1]}.${m[2]}.${m[3]}.0/24`] = (count[`${m[1]}.${m[2]}.${m[3]}.0/24`] || 0) + 1;
    }
    return { cidr: Object.keys(count).sort((a, b) => count[b] - count[a])[0] || null };
  });
  // A network scan (before /printers/:id, which would take "discover" for an id): a few made-up printers at fixed
  // places in the range, skipping addresses the farm's printers have. Two share MainsailOS's default hostname; the
  // Trident is on both cable and Wi-Fi, so it's listed once, at its wired IP.
  on("GET", "/printers/discover", async (_, __, q) => {
    const cidr = (q.get("cidr") || "").trim();
    const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?:\/(\d{1,2}))?$/.exec(cidr);
    if (cidr.includes(":")) throw new HttpError(422, "Only IPv4 ranges can be scanned, like 192.168.1.0/24.");
    if (!m || m.slice(1, 5).some((o) => Number(o) > 255) || Number(m[5] ?? 32) > 32) throw new HttpError(422, `'${cidr}' isn't a network range. Write it like 192.168.1.0/24.`);
    const bits = Number(m[5] ?? 32);
    const [a, b] = m.slice(1, 3).map(Number); // the farm's own network only, as the real API (is_private)
    const own = a === 10 || a === 127 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 169 && b === 254);
    if (!own || bits < 8) throw new HttpError(422, "Only your own network can be scanned: a range starting 10., 172.16 to 172.31, or 192.168.");
    if (2 ** (32 - bits) > 1024) throw new HttpError(422, `That range has ${2 ** (32 - bits)} addresses. Scan 1024 or fewer at a time (a /22 or smaller).`);
    await new Promise((done) => setTimeout(done, 2000)); // a real scan of a /24 takes a few seconds
    const start = (m.slice(1, 5).reduce((n, o) => n * 256 + Number(o), 0) >>> (32 - bits)) * 2 ** (32 - bits);
    const ipAt = (n) => [24, 16, 8, 0].map((s) => (n >>> s) & 255).join(".");
    // active printers' addresses are skipped; one found at a decommissioned printer's is listed with that printer
    const known = new Set(farm.printers.filter((p) => !p.decommissioned).flatMap((p) => [p.wired_ip, p.wireless_ip]).filter(Boolean));
    const retired = new Map(farm.printers.filter((p) => p.decommissioned).flatMap((p) => [p.wired_ip, p.wireless_ip].filter(Boolean).map((h) => [h, p])));
    const was = (f) => [f.ip, f.wired_ip, f.wireless_ip].map((h) => h && retired.get(h)).find(Boolean);
    const sample = [ // [offset, hostname, firmware, needs a key, link, the other link's offset]
      [31, "mainsailos", "Klipper", false, "wired", null],
      [32, "mainsailos", "Klipper", false, "wireless", null],
      [40, "trident-300", "Kalico", false, "wired", 41],
      [77, null, null, true, null, null],
      [129, null, "Prusa", true, null, null], // a Core One: PrusaLink wants its password, so it gives no name
    ];
    const inRange = (offset) => offset < 2 ** (32 - bits) - (bits < 31 ? 1 : 0);
    return sample
      .filter(([offset]) => inRange(offset))
      .map(([offset, hostname, firmware, needsKey, link, other]) => {
        const ip = ipAt(start + offset);
        const otherIp = other != null && inRange(other) ? ipAt(start + other) : null;
        if (firmware === "Prusa") {
          return {
            ip, connection_type: "prusalink", address: `http://${ip}`, web_url: `http://${ip}/`, hostname, firmware,
            version: null, state: null, needs_api_key: needsKey, link: null, wired_ip: null, wireless_ip: null,
          };
        }
        return {
          ip, connection_type: "moonraker", address: `http://${ip}:7125`, web_url: `http://${ip}/`, hostname, firmware,
          version: needsKey ? null : "v0.9.3", state: needsKey ? null : "ready", needs_api_key: needsKey, link,
          wired_ip: link === "wired" ? ip : null, wireless_ip: link === "wireless" ? ip : otherIp,
        };
      })
      .filter((f) => ![f.ip, f.wired_ip, f.wireless_ip].some((h) => h && known.has(h)))
      .map((f) => ({ ...f, decommissioned_id: was(f)?.id ?? null, decommissioned_name: was(f)?.name ?? null }));
  });
  on("GET", "/printers/:id", ({ id }) => printerOut(printer(id)));
  on("POST", "/printers", (_, body) => {
    if (!body.name?.trim()) throw new HttpError(422, "A printer needs a name");
    if (farm.printers.some((p) => p.name === body.name.trim())) throw new HttpError(409, `A printer named '${body.name}' already exists — name is the unique key, not IP`);
    const p = { id: farm.nextIds.printer++, name: body.name.trim(), kind: body.kind, wired_ip: body.wired_ip, wireless_ip: body.wireless_ip, decommissioned: false, created_at: iso(nowUnix()), moonraker: null, notes: "", serviceHoursSince: null, serviceHistory: [] };
    if (body.connection_type === "prusalink") {
      p.prusalink = { reachable: true, firmware: "6.2.0", username: body.prusalink_username || "maker", hasPassword: !!body.prusalink_password, password: body.prusalink_password || null, url: body.prusalink_url || null };
    } else {
      p.moonraker_url_override = body.moonraker_url || null;
      p.apiKey = body.moonraker_api_key || null;
    }
    p.cameraAddress = body.camera_address || null;
    farm.printers.push(p);
    return [201, printerOut(p)];
  });
  // As the real API: only a decommissioned printer, and only once no 3MF files are kept for it
  on("DELETE", "/printers/:id", ({ id }, _b, q) => {
    requireConfirm(q);
    const p = printer(id);
    if (!p.decommissioned) throw new HttpError(409, `${p.name} is still in use. Decommission it first (Edit), then it can be deleted.`);
    const n = farm.bundles.filter((b) => b.printer_id === p.id).length;
    if (n) throw new HttpError(409, `${p.name} still has ${n} 3MF file${n !== 1 ? "s" : ""}. Delete ${n !== 1 ? "them" : "it"} from its page first, then the printer can be deleted.`);
    farm.printers = farm.printers.filter((x) => x !== p);
    return [204, null];
  });
  on("PATCH", "/printers/:id", ({ id }, body) => {
    const p = printer(id);
    for (const k of ["name", "kind", "wired_ip", "wireless_ip", "decommissioned"]) if (k in body && body[k] !== undefined) p[k] = body[k];
    if ("moonraker_url" in body) p.moonraker_url_override = body.moonraker_url || null;
    if ("camera_address" in body) p.cameraAddress = body.camera_address || null;
    if (body.moonraker_api_key != null) p.apiKey = body.moonraker_api_key || null;
    if (body.connection_type === "moonraker") delete p.prusalink;
    if (body.connection_type === "prusalink" && !p.prusalink) p.prusalink = { reachable: true, firmware: "6.2.0", username: "maker", hasPassword: false, url: null };
    if (p.prusalink) {
      if ("prusalink_url" in body) p.prusalink.url = body.prusalink_url || null;
      if (body.prusalink_username != null) p.prusalink.username = body.prusalink_username.trim() || "maker";
      if (body.prusalink_password != null) {
        p.prusalink.hasPassword = !!body.prusalink_password;
        p.prusalink.password = body.prusalink_password || null;
      }
    }
    return printerOut(p);
  });
  on("PUT", "/printers/:id/notes", ({ id }, body) => {
    const p = printer(id);
    saveNotes(p, body, { text: "notes", rev: "notesRevision", at: "notesUpdatedAt" });
    return printerOut(p);
  });
  // Printer profiles (a printer's presets in the slicer): added, renamed and removed by hand, with the real API's rules
  const subPrinterName = (body) => {
    const name = String(body.name ?? "").trim();
    if (!name) throw new HttpError(422, "A printer profile needs a name");
    if (name.length > 120) throw new HttpError(422, "A printer profile's name can be at most 120 characters");
    return name;
  };
  const subPrinterOf = (p, subId) => {
    const s = farm.subPrinters.find((x) => x.id === Number(subId) && x.printer_id === p.id);
    if (!s) throw new HttpError(404, `No printer profile with id ${subId} on this printer`);
    return s;
  };
  const newSubPrinter = (p, name) => {
    const s = { id: farm.nextIds.subPrinter++, printer_id: p.id, name, aliases: [], parts: defaultParts(() => farm.nextIds.part++) };
    farm.subPrinters.push(s);
    return s;
  };
  // from now on a 3MF with this preset goes to s (and no longer to another of the printer's that had it)
  const remember = (s, preset) => {
    if (!preset || preset === s.name || (s.aliases || []).includes(preset)) return;
    for (const o of farm.subPrinters) if (o.printer_id === s.printer_id) o.aliases = (o.aliases || []).filter((a) => a !== preset);
    s.aliases = [...(s.aliases || []), preset];
  };
  // the printer profile a preset goes to: one known by that name, else the one called that
  const knownAs = (p, preset) =>
    farm.subPrinters.find((s) => s.printer_id === p.id && (s.aliases || []).includes(preset)) ||
    farm.subPrinters.find((s) => s.printer_id === p.id && s.name === preset);
  // which printer profile a new 3MF version goes to: picked on upload, else the one its preset goes to (as the real API)
  const subPrinterFor = (p, preset, fields = {}) => {
    let s = null;
    if (fields.sub_printer_id) {
      s = farm.subPrinters.find((x) => x.id === Number(fields.sub_printer_id) && x.printer_id === p.id);
      if (!s) throw new HttpError(422, `That printer profile isn't one of ${p.name}'s`);
    } else if (fields.new_sub_printer_name?.trim()) {
      const name = fields.new_sub_printer_name.trim().slice(0, 120);
      s = farm.subPrinters.find((x) => x.printer_id === p.id && x.name === name) || newSubPrinter(p, name);
    } else if (preset) {
      s = knownAs(p, preset) || newSubPrinter(p, preset);
    }
    if (s && preset) remember(s, preset);
    return s;
  };
  const nameTaken = (p, name, except) => {
    if (farm.subPrinters.some((s) => s.printer_id === p.id && s.name === name && s !== except)) {
      throw new HttpError(409, `${p.name} already has a printer profile named '${name}'`);
    }
  };
  on("POST", "/printers/:id/sub-printers", ({ id }, body) => {
    const p = printer(id);
    const name = subPrinterName(body);
    nameTaken(p, name);
    newSubPrinter(p, name);
    return [201, printerOut(p)];
  });
  // A copy with its parts, named as given or "<name> - copy" (- copy 2... when taken); its 3MFs and the default stay
  on("POST", "/printers/:id/sub-printers/:subId/copy", ({ id, subId }, body) => {
    const p = printer(id);
    const s = subPrinterOf(p, subId);
    let name = body?.name != null ? subPrinterName(body) : null;
    for (let n = 1; name == null; n++) {
      const tail = n === 1 ? " - copy" : ` - copy ${n}`;
      const candidate = s.name.slice(0, 120 - tail.length).trimEnd() + tail;
      if (!farm.subPrinters.some((x) => x.printer_id === p.id && x.name === candidate)) name = candidate;
    }
    nameTaken(p, name);
    const copy = newSubPrinter(p, name);
    copy.parts = s.parts.map((part) => ({ ...part, id: farm.nextIds.part++ }));
    // its printer settings, as the original's newest 3MF has them (or the ones it was copied with itself)
    const newest = farm.bundles.flatMap((b) => b.versions.map((v) => ({ b, v })))
      .filter(({ v }) => v.sub_printer_id === s.id)
      .sort((x, y) => Date.parse(y.v.uploaded_at) - Date.parse(x.v.uploaded_at))[0];
    if (newest) {
      copy.settings_copy = {
        copied_from: s.name, from_file: `${newest.v.filename || newest.b.name} · v${newest.v.version}`,
        copied_at: new Date().toISOString(), settings: { ...(farm.versionSettings[newest.v.id] || {}) },
      };
    } else if (s.settings_copy) {
      copy.settings_copy = { ...s.settings_copy, copied_from: s.name, copied_at: new Date().toISOString() };
    }
    return [201, printerOut(p)];
  });
  on("GET", "/printers/:id/sub-printers/:subId/settings-copy", ({ id, subId }) => {
    const s = subPrinterOf(printer(id), subId);
    if (!s.settings_copy) throw new HttpError(404, "This printer profile has no copied printer settings");
    return s.settings_copy;
  });
  on("PATCH", "/printers/:id/sub-printers/:subId", ({ id, subId }, body) => {
    const p = printer(id);
    const s = subPrinterOf(p, subId);
    const name = subPrinterName(body);
    nameTaken(p, name, s);
    const old = s.name;
    s.name = name;
    s.aliases = (s.aliases || []).filter((a) => a !== name); // its name now, not a name it was known by
    remember(s, old);
    return printerOut(p);
  });
  on("DELETE", "/printers/:id/sub-printers/:subId", ({ id, subId }, _b, q) => {
    requireConfirm(q);
    const p = printer(id);
    const s = subPrinterOf(p, subId);
    for (const b of farm.bundles) for (const v of b.versions) if (v.sub_printer_id === s.id) v.sub_printer_id = null;
    farm.subPrinters = farm.subPrinters.filter((x) => x !== s);
    if (p.defaultSubPrinterId === s.id) p.defaultSubPrinterId = null; // no default any more
    return printerOut(p);
  });
  on("PUT", "/printers/:id/default-sub-printer", ({ id }, body) => {
    const p = printer(id);
    p.defaultSubPrinterId = body.sub_printer_id == null ? null : subPrinterOf(p, body.sub_printer_id).id;
    return printerOut(p);
  });
  // A printer profile's parts (its Printer parts page), with the real API's checks; each change answers the whole list
  const partFields = (body) => {
    const part = String(body.part ?? "").trim();
    if (!part) throw new HttpError(422, "Say what the part is (e.g. Hotend)");
    const text = (v) => String(v ?? "").trim() || null;
    if (body.installed_on != null && !/^\d{4}-\d{2}-\d{2}$/.test(body.installed_on)) throw new HttpError(422, "The installed date isn't a date");
    return { part: part.slice(0, 120), make: text(body.make), model: text(body.model), installed_on: body.installed_on || null, note: text(body.note), in_name: body.in_name === true };
  };
  // a default part (Toolhead, Hotend...) keeps its name
  const keepDefaultName = (part, fields) => {
    if (DEFAULT_PARTS.some(([name]) => name === part.part) && fields.part !== part.part) {
      throw new HttpError(422, `${part.part} is one of the default parts, so its name can't be changed`);
    }
  };
  const partOf = (s, partId) => {
    const found = s.parts.find((x) => x.id === Number(partId));
    if (!found) throw new HttpError(404, `No part with id ${partId} on this printer profile`);
    return found;
  };
  on("GET", "/printers/:id/sub-printers/:subId/parts", ({ id, subId }) => subPrinterOf(printer(id), subId).parts);
  on("POST", "/printers/:id/sub-printers/:subId/parts", ({ id, subId }, body) => {
    const s = subPrinterOf(printer(id), subId);
    s.parts.push({ id: farm.nextIds.part++, ...partFields(body) });
    return [201, s.parts];
  });
  // The whole list at once (the page's Save): with an id it's changed, without it's added, left out it's removed
  // (confirm=true). All of it or nothing.
  on("PUT", "/printers/:id/sub-printers/:subId/parts", ({ id, subId }, body, q) => {
    const s = subPrinterOf(printer(id), subId);
    const rows = Array.isArray(body) ? body : [];
    const kept = new Set(rows.map((r) => r.id).filter((x) => x != null));
    if (s.parts.some((x) => !kept.has(x.id)) && q.get("confirm") !== "true") throw new HttpError(409, "Saving removes parts: say confirm=true");
    if (kept.size !== rows.filter((r) => r.id != null).length) throw new HttpError(422, "The same part is in the list twice");
    const checked = rows.map((r) => {
      const fields = partFields(r);
      if (r.id == null) return { fields };
      const part = partOf(s, r.id);
      keepDefaultName(part, fields);
      return { part, fields };
    });
    const changed = checked.filter((r) => r.part).map((r) => Object.assign(r.part, r.fields));
    s.parts = [...changed.sort((a, b) => a.id - b.id), ...checked.filter((r) => !r.part).map((r) => ({ id: farm.nextIds.part++, ...r.fields }))];
    return s.parts;
  });
  on("PUT", "/printers/:id/sub-printers/:subId/parts/:partId", ({ id, subId, partId }, body) => {
    const s = subPrinterOf(printer(id), subId);
    const part = partOf(s, partId);
    const fields = partFields(body);
    keepDefaultName(part, fields);
    Object.assign(part, fields);
    return s.parts;
  });
  on("DELETE", "/printers/:id/sub-printers/:subId/parts/:partId", ({ id, subId, partId }, _b, q) => {
    requireConfirm(q);
    const s = subPrinterOf(printer(id), subId);
    const gone = partOf(s, partId);
    s.parts = s.parts.filter((x) => x !== gone);
    return s.parts;
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
    requireConfirm(q);
    const m = model(id);
    const used = farm.bundles.filter((b) => b.source_model_ids.includes(m.id));
    if (used.length && q.get("cascade") !== "true") throw new HttpError(409, `${used.length} 3MF file(s) were sliced from this model — pass cascade=true to delete them too`);
    farm.bundles = farm.bundles.filter((b) => !b.source_model_ids.includes(m.id));
    farm.models = farm.models.filter((x) => x.id !== m.id);
    for (const p of farm.projects) p.source_model_ids = p.source_model_ids.filter((x) => x !== m.id); // out of every project
    for (const p of farm.projects) p.bundle_ids = p.bundle_ids.filter((x) => farm.bundles.some((b) => b.id === x));
    return [204, null];
  });
  on("DELETE", "/source-models/:id/versions/:v", ({ id, v }, _b, q) => {
    requireConfirm(q);
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
  // The mockup can't open a 3MF: it reads the printer from the file's name ("VT_1190_-_…" is the VT 1190) and takes
  // the preset and settings that printer's 3MFs mostly use. Uploads are kept as versions with those settings.
  const squash = (t) => t.toLowerCase().replace(/[^a-z0-9]/g, "");
  const readThreemf = (body) => {
    const file = (body.files || []).find((f) => /\.3mf$/i.test(f));
    if (!file) throw new HttpError(422, "Drop a .3mf file");
    const p = [...farm.printers].sort((a, b) => b.name.length - a.name.length).find((x) => squash(file).startsWith(squash(x.name)));
    const versions = p ? farm.bundles.filter((b) => b.printer_id === p.id).flatMap((b) => b.versions) : [];
    const count = {};
    for (const v of versions) {
      const preset = farm.versionSettings[v.id]?.printer_settings_id;
      if (preset) count[preset] = (count[preset] || 0) + 1;
    }
    const preset = Object.keys(count).sort((a, b) => count[b] - count[a])[0] || null;
    const like = [...versions].reverse().find((v) => farm.versionSettings[v.id]?.printer_settings_id === preset) || versions[0];
    return { file, printer: p, preset, like };
  };
  const addVersion = (b, read, body, number) => {
    const p = printer(b.printer_id);
    const sub = subPrinterFor(p, read.preset, body.fields);
    const gcode = (body.files || []).find((f) => /\.(b?gcode)$/i.test(f));
    const id = farm.nextIds.bundleVersion++;
    farm.versionSettings[id] = { ...(read.like ? farm.versionSettings[read.like.id] : {}), ...(read.preset ? { printer_settings_id: read.preset } : {}) };
    b.versions.unshift({
      id, version: number, filename: number > 1 ? read.file.replace(/\.3mf$/i, ` ver ${number}.3mf`) : read.file, slicer_family: "prusaslicer",
      slicer_display_name: read.like?.slicer_display_name || "PrusaSlicer 2.9.6", printer_profile_name: p.name, uploaded_at: iso(nowUnix()),
      monument: number === 1, monument_note: number === 1 ? "Initial upload" : null, full_files_retained: true,
      thumbnail_path: read.like?.thumbnail_path || null, thumb: read.like?.thumb || null,
      gcode_name: gcode ? read.file.replace(/\.3mf$/i, gcode.slice(gcode.lastIndexOf(".")).toLowerCase()) : null, sub_printer_id: sub ? sub.id : null,
    });
  };
  on("POST", "/bundles/inspect", (_, body) => {
    const read = readThreemf(body);
    return {
      printer_profile_name: read.printer ? read.printer.name : null, printer_preset_name: read.preset,
      slicer_display_name: read.like?.slicer_display_name || "PrusaSlicer 2.9.6", matched_printer: read.printer ? printerOut(read.printer) : null,
    };
  });
  on("POST", "/bundles", (_, body) => {
    const read = readThreemf(body);
    const f = body.fields || {};
    const p = f.printer_id ? printer(f.printer_id) : read.printer;
    if (!p) throw new HttpError(422, "Pick which printer this file belongs to");
    const b = {
      id: Math.max(0, ...farm.bundles.map((x) => x.id)) + 1, printer_id: p.id, created_at: iso(nowUnix()),
      source_model_ids: JSON.parse(f.source_model_ids || "[]"), versions: [], starred_version_id: null, notes: "", notes_revision: 0, notes_updated_at: null,
    };
    addVersion(b, { ...read, printer: p }, body, 1);
    farm.bundles.push(b);
    return [201, bundleOut(b)];
  });
  // When none of a 3MF's versions is starred, its newest is (never version 1, the initial upload)
  const starNewestIfNone = (b) => {
    const newest = b.versions.reduce((a, v) => (!a || v.version > a.version ? v : a), null);
    if (b.starred_version_id == null && newest && newest.version > 1) b.starred_version_id = newest.id;
  };
  on("POST", "/bundles/:id/versions", ({ id }, body) => {
    const b = bundle(id);
    addVersion(b, readThreemf(body), body, (b.versions[0]?.version || 0) + 1);
    starNewestIfNone(b);
    return [201, bundleOut(b)];
  });
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
  on("DELETE", "/bundles/versions/:id", ({ id }, _b, q) => {
    requireConfirm(q);
    const { b, v } = version(id);
    b.versions = b.versions.filter((x) => x.id !== v.id);
    if (b.starred_version_id === v.id) {
      b.starred_version_id = null; // its star moves to the newest one left
      starNewestIfNone(b);
    }
    if (!b.versions.length) farm.bundles = farm.bundles.filter((x) => x.id !== b.id);
    return [204, null];
  });
  on("DELETE", "/bundles/:id", ({ id }, _b, q) => {
    requireConfirm(q);
    farm.bundles = farm.bundles.filter((b) => b.id !== Number(id));
    for (const p of farm.projects) p.bundle_ids = p.bundle_ids.filter((x) => x !== Number(id)); // out of every project
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
    if (!p.moonraker) return { webcams: [], error: "This printer has no IP address or Moonraker address set.", board: null };
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
    if (!p.moonraker?.reachable) return { ...nothing, error: p.moonraker?.error || "This printer has no IP address or Moonraker address set." };
    const job = (farm.jobs[p.id] || []).find((j) => j.status === "in_progress");
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
    // where the server keeps each month's record: the folder chosen in Settings, else "farm cost" above the STL folder
    records: {
      folder: farm.farmCostFolder || FARM_COST_DEFAULT, problem: null,
      saved: ["farmhand - farm cost - oct 2026.csv", "farmhand - farm cost - sep 2026.csv"],
    },
  }));
  const FARM_COST_DEFAULT = "/data/nas/farm-nas/farm cost";
  const farmCostLocation = () => ({
    path: farm.farmCostFolder || FARM_COST_DEFAULT, is_default: !farm.farmCostFolder, default_path: FARM_COST_DEFAULT,
    status: { exists: true, writable: true, marker_ok: true, ready: true },
  });
  on("GET", "/farm-cost/location", () => farmCostLocation());
  // The save location: one place on the NAS for everything, as the server sets it up (connecting to the share, and
  // using or making STL, 3MF, Projects, Farm cost and Farmhand Configs inside it). A password of "wrong" is refused, to
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
      farm_cost: farm.farmCostFolder || FARM_COST_DEFAULT, config: farm.settingsFolder || null,
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
    farm.farmCostFolder = `${base}/Farm cost`;
    farm.settingsFolder = `${base}/Farmhand Configs`;
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
      const d = new Date(t * 1000);
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
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
    requireConfirm(q, "Deleting is permanent (in Mainsail too) — pass confirm=true to proceed");
    const p = printer(id);
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

  // ------------------------------------------------------------------ settings, storage, shares
  const location = (path) => ({
    path, default_path: path.includes("models") ? "/data/storage/source_models" : path.includes("projects") ? "/data/storage/projects" : "/data/storage/bundles", is_default: false,
    status: { exists: true, writable: true, marker_ok: true, ready: true, free_bytes: 2.1e12, total_bytes: 4e12, separate_volume: true },
  });
  const storageOut = () => ({ browse_root: "/data", stl: location(farm.storage.stl), threemf: location(farm.storage.threemf), project: location(farm.storage.project), outside: { stl: 0, threemf: 0, project: 0 } });
  const configLocation = () => ({
    path: farm.settingsFolder, is_set: !!farm.settingsFolder,
    status: farm.settingsFolder ? { exists: true, writable: true, marker_ok: true, ready: true } : null,
    file: farm.settingsFolder ? { exists: true, modified_at: iso(nowUnix() - 300), size: 2841 } : null,
    last_write: { ok: true, error: null, at: iso(nowUnix() - 300) },
  });
  on("GET", "/settings/config", () => ({ config: farm.config, location: configLocation() }));
  on("PUT", "/settings/config", (_, body) => {
    if (body.appearance) farm.config.appearance = { ...farm.config.appearance, ...body.appearance };
    const pricesBefore = prices(); // the average cost and its history before this save
    if (body.preferences) farm.config.preferences = { ...farm.config.preferences, ...body.preferences };
    if (body.preferences?.tool_links) {
      // as the server does: trimmed, and web addresses only
      farm.config.preferences.tool_links = (Array.isArray(body.preferences.tool_links) ? body.preferences.tool_links : [])
        .filter((l) => l && typeof l === "object")
        .map((l) => ({ name: typeof l.name === "string" ? l.name.trim() : "", url: typeof l.url === "string" ? l.url.trim() : "" }))
        .filter((l) => /^https?:\/\/[^\s/]+/i.test(l.url) && l.url.length <= 2000 && l.name.length <= 100)
        .slice(0, 200);
    }
    if (body.preferences && "energy_price_per_kwh" in body.preferences) {
      // as the server does: a number from 0 to 100, else not set
      // ...and, as the server does, it counts from the month the page says it is on; earlier months keep theirs
      const v = body.preferences.energy_price_per_kwh;
      const price = typeof v === "number" && v >= 0 && v <= 100 ? Math.round(v * 100000) / 100000 : null;
      const month = /^\d{4}-\d{2}$/.test(body.preferences.energy_price_from || "") ? body.preferences.energy_price_from : monthOf(nowUnix());
      const next = withNewAverage(pricesBefore, price, month);
      Object.assign(farm.config.preferences, { energy_price_per_kwh: price, energy_price_history: next.history });
    }
    delete farm.config.preferences.energy_price_from;
    if (body.preferences && "energy_price_months" in body.preferences) {
      const months = {};
      for (const [k, v] of Object.entries(body.preferences.energy_price_months || {})) {
        if (/^\d{4}-(0[1-9]|1[0-2])$/.test(k) && typeof v === "number" && v >= 0 && v <= 100) months[k] = Math.round(v * 100000) / 100000;
      }
      farm.config.preferences.energy_price_months = months;
    }
    return { config: farm.config, mirror: { ok: true, skipped: !farm.settingsFolder, path: farm.settingsFolder, error: null } };
  });
  on("GET", "/settings/config/location/inspect", (_, _b, q) => ({ path: q.get("path"), file_exists: false, file_valid: null, modified_at: null, summary: null, error: null }));
  on("PUT", "/settings/config/location", (_, body) => {
    farm.settingsFolder = body.path || null;
    return { saved: true, needs_choice: false, found: null, restored: null, location: configLocation() };
  });
  on("POST", "/settings/config/save-now", () => ({ ok: true, skipped: false, path: farm.settingsFolder, error: null }));
  // Save all: with no folder chosen, "farmhand configs" beside the STL folder (as the server does)
  on("POST", "/settings/config/save-all", () => {
    if (!farm.settingsFolder) farm.settingsFolder = farm.storage.stl.replace(/\/[^/]*$/, "") + "/farmhand configs";
    return {
      saved: true, needs_choice: false, found: null, restored: null, location: configLocation(),
      mirror: { ok: true, skipped: false, path: farm.settingsFolder, error: null },
    };
  });
  on("POST", "/settings/config/restore", () => ({ restored: ["appearance", "display preferences"], shares_added: [], shares_kept: ["farm-nas"], needs_password: [], warnings: [], records: null }));

  on("GET", "/settings/storage", () => storageOut());
  on("PUT", "/settings/storage", (_, body) => {
    if ("stl_path" in body) farm.storage.stl = body.stl_path || "/data/storage/source_models";
    if ("threemf_path" in body) farm.storage.threemf = body.threemf_path || "/data/storage/bundles";
    if ("project_path" in body) farm.storage.project = body.project_path || "/data/storage/projects";
    return storageOut();
  });
  on("GET", "/settings/storage/browse", (_, _b, q) => {
    const path = q.get("path") || "/data";
    const tree = { "/data": ["nas", "storage"], "/data/nas": ["farm-nas"], "/data/nas/farm-nas": ["3mf", "farmhand-settings", "models", "projects"], [SCAN_ROOT]: Object.keys(scanFolders), "/data/storage": ["bundles", "projects", "source_models"] };
    const parent = path === "/data" ? null : path.split("/").slice(0, -1).join("/") || "/data";
    return { path, root: "/data", parent, entries: (tree[path] || []).map((name) => ({ name, path: `${path}/${name}`, is_mount: path === "/data/nas" })) };
  });
  on("POST", "/settings/storage/folders", () => { throw notInMockup("Making folders"); });
  on("POST", "/settings/storage/migrate", () => ({ moved_stl: 0, moved_threemf: 0, moved_project: 0, missing: [], failed: [] }));
  const capability = { ok: true, smb: true, nfs: true, message: null, smb_message: null, nfs_message: null };
  on("GET", "/settings/storage/shares", () => ({ shares: farm.shares, capability }));
  on("POST", "/settings/storage/shares", () => { throw notInMockup("Connecting a network share"); });
  on("PATCH", "/settings/storage/shares/:id", () => { throw notInMockup("Changing a network share"); });
  on("POST", "/settings/storage/shares/:id/connect", ({ id }) => farm.shares.find((s) => s.id === Number(id)) || fail404("Share not found"));
  on("DELETE", "/settings/storage/shares/:id", ({ id }, _b, q) => {
    requireConfirm(q, "Pass confirm=true to proceed");
    farm.shares = farm.shares.filter((s) => s.id !== Number(id));
    return [204, null];
  });

  // ------------------------------------------------------------------ files: preview images and downloads
  const png = (slug) => (slug ? readFileSync(join(FIXTURES, "thumbs", `${slug.startsWith("stl-") ? slug : `3mf-${slug}`}.png`)) : null);
  const fileRoutes = [
    [/^\/bundles\/versions\/(\d+)\/thumbnail$/, (m) => png(version(m[1]).v.thumb)],
    [/^\/source-models\/(\d+)\/versions\/(\d+)\/thumbnail$/, (m) => png(model(m[1]).versions.find((v) => v.version === Number(m[2]))?.thumb)],
    [/^\/projects\/(\d+)\/(doc|cad|stl|threemf)\/(\d+)\/versions\/(\d+)\/preview$/, (m) => png(fileVersion(m[1], m[2], m[3], m[4]).thumb)],
  ];
  const downloadRoutes = [
    [/^\/bundles\/versions\/(\d+)\/download\/(3mf|gcode)$/, (m) => [version(m[1]).v.filename.replace(/\.3mf$/, m[2] === "gcode" ? ".gcode" : ".3mf")]],
    [/^\/source-models\/(\d+)\/versions\/(\d+)\/download$/, (m) => [model(m[1]).name]],
    [/^\/projects\/(\d+)\/(doc|cad|stl|threemf)\/(\d+)\/versions\/(\d+)\/download$/, (m) => [fileVersion(m[1], m[2], m[3], m[4]).filename]],
    [/^\/projects\/(\d+)\/threemf\/(\d+)\/versions\/(\d+)\/gcode$/, (m) => [fileVersion(m[1], "threemf", m[2], m[3]).gcode || fail404("No G-code")]],
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
            // a project file opened in the browser: shown (as the real one is), here as a stand-in
            const view = url.pathname.match(/^\/projects\/(\d+)\/(doc|cad|stl|threemf)\/(\d+)\/versions\/(\d+)\/view$/);
            if (view) {
              const name = fileVersion(view[1], view[2], view[3], view[4]).filename;
              res.setHeader("Content-Disposition", `inline; filename="${name}"`);
              return send(200, `Farmhand mockup: ${name} would open here. The real file comes from the real backend.\n`, "text/plain");
            }
          }
          const chunks = [];
          for await (const chunk of req) chunks.push(chunk);
          const raw = Buffer.concat(chunks).toString("utf-8");
          let body = {};
          if (raw && (req.headers["content-type"] || "").includes("application/json")) body = JSON.parse(raw);
          // an upload: only the names of the files sent, and its text fields, are kept (the mockup doesn't store files)
          if ((req.headers["content-type"] || "").includes("multipart/form-data")) {
            body = {
              files: [...raw.matchAll(/filename="([^"]*)"/g)].map((m) => m[1]),
              fields: Object.fromEntries([...raw.matchAll(/name="([^"]+)"\r\n\r\n([^\r]*)\r\n/g)].map((m) => [m[1], m[2]])),
            };
          }
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
