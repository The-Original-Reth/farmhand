// Models and 3MFs: their versions, uploads (a 3MF read from its file name), renames, notes, stars and deletes.
import { HttpError, notInMockup, nowUnix } from "../core.js";
import { HOUR, iso } from "../data.js";

export function libraryRoutes(ctx) {
  const { bundle, bundleOut, farm, liveJob, model, modelOut, on, printer, printerOut, reachMoonraker, requireConfirm, runningJob, saveNotes, subPrinterFor, version, versionDetail } = ctx;

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
    reachMoonraker(p);
    if (runningJob(p)) throw new HttpError(409, `${p.name} is printing, so a new print can't be started.`);
    return { sent: `gcodes/${v.gcode_name}`, printer: p.name };
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
  return { cleanName, extensionOf, squash, readThreemf, addVersion, starNewestIfNone };
}
