// Projects: made, listed, renamed and deleted; their own files, the models, 3MFs and printers they use, their BOM,
// and Scan projects.
import { HttpError, nowUnix } from "../core.js";
import { iso } from "../data.js";

export function projectsRoutes(ctx) {
  const { bundle, fail404, farm, model, on, printer, requireConfirm } = ctx;

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
    return [201, importSample(name, files)];
  });
  // Scan projects' projects folder: every sample folder that isn't a project yet comes in (as the server does with the
  // project files folder's folders)
  on("POST", "/projects/scan-projects-folder", () => {
    const imported = Object.entries(scanFolders)
      .filter(([name]) => !farm.projects.some((p) => p.name.toLowerCase() === name.toLowerCase()))
      .map(([name, files]) => importSample(name, files));
    return { imported, skipped: [], models: [], threemfs: [], library_skipped: [] };
  });
  // One sample folder made a project, its files sorted by kind as the API sorts them: { project_id, name, files, warnings }
  function importSample(name, files) {
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
    return { project_id: p.id, name, files: counts, warnings: [] };
  }
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
    const b = bundle(bid);
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
    linkPrinter(p, printer(pid).id);
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
    const to = farm.printers.find((x) => x.id === f.printer_id);
    if (!to) throw new HttpError(422, "This 3MF has no printer to send it to.");
    return { sent: `gcodes/${ver.gcode}`, printer: to.name };
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
  return { project, projectName, filesOut, projectOut, SCAN_ROOT, scanFolders, scanKind, scanCounts, scanFolder, importSample, linkPrinter, countFields, cleanComponent, componentField, projectGcodeVersion, bomPartFields, withVersion, previewable, KIND, kindOf, projectFile, fileVersion, isStl, addFileVersion };
}
