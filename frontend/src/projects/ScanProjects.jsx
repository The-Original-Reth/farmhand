import { useEffect, useRef, useState } from "react";
import { FolderOpen } from "lucide-react";
import { checkProjectFiles, errorText, importProjectFolder, scanProjectFolder, scanProjectsFolder } from "../api.js";
import { c, fs, ui } from "../theme.js";
import { useData } from "../data.jsx";
import { readStored, writeStored } from "../lib/storage.js";
import { Modal } from "../components/common/dialogs.jsx";
import { SegmentedToggle } from "../components/common/fields.jsx";
import { Badge } from "../components/common/ui.jsx";
import { FolderPicker } from "../storage/FolderPicker.jsx";
import { monoText, panelBox, primaryButton, toolButton, uiText } from "../styles.js";
import { plural } from "../lib/format.js";

// Scan projects: the project files folder scanned at once (every project folder there that isn't one of this Farmhand's
// projects brought in: another Farmhand's sharing it, or one dropped in by hand), another folder's project folders
// brought in (copied), and checking the project files Farmhand keeps against what's on the disk.

const FOLDER_KEY = "farmhand.projectScanFolder"; // the folder last scanned, remembered in this browser

// "3 STLs, 1 3MF, 2 documents": what a folder holds, by kind
const KIND_WORDS = [
  ["stl", "STL"], ["threemf", "3MF"], ["gcode", "G-code"], ["cad", "CAD file"], ["doc", "document"],
];
const whatsIn = (files) =>
  KIND_WORDS.filter(([k]) => files[k]).map(([k, word]) => plural(files[k], word)).join(", ") || "no files";

export function ScanProjectsDialog({ onClose }) {
  const [part, setPart] = useState("folder");
  return (
    <Modal title="Scan projects" width={680} onClose={onClose}>
      <SegmentedToggle
        options={[
          { value: "folder", label: "Projects folder" },
          { value: "import", label: "Another folder" },
          { value: "check", label: "Check projects" },
        ]}
        value={part}
        onChange={setPart}
      />
      {part === "folder" ? <ProjectsFolder /> : part === "import" ? <ImportFolders /> : <CheckProjects />}
    </Modal>
  );
}

// The project files folder, scanned as soon as the dialog opens: every project folder in it that isn't one of this
// Farmhand's projects comes in, its files used where they are. (It's also scanned on its own every few minutes.)
function ProjectsFolder() {
  const { refresh } = useData();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await scanProjectsFolder();
      setResult(r);
      if (r.imported.length) await refresh();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const started = useRef(false); // once, when the dialog opens (React runs this twice in development)
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    run();
  }, []);
  return (
    <div data-testid="scan-projects-folder">
      <div style={uiText(12, c.textFaint, { lineHeight: 1.6, marginBottom: 12 })}>
        The models and 3MF files another Farmhand sharing the folders has come in first (a 3MF once its printer is here), then
        every project folder in the project files folder that isn't a project here yet, its files used where they are: one another Farmhand sharing the folder keeps (with its name, files, versions, notes, sub-components and parts
        list), or a folder you dropped in (named after it, its files sorted by kind). It's also done on its own every few
        minutes.
      </div>
      {error && <div style={uiText(12, c.amber, { lineHeight: 1.5, marginBottom: 10 })}>{error}</div>}
      {busy && <div style={uiText(13, c.textFaint, { marginBottom: 10 })}>Scanning the projects folder…</div>}
      {result && !busy && (
        <div data-testid="scan-projects-folder-result" style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 12 }}>
          {result.imported.length === 0 && result.skipped.length === 0 && result.models.length === 0 && result.threemfs.length === 0 && (
            <div style={uiText(13, c.textMuted)}>Nothing new: every project, model and 3MF there is here already.</div>
          )}
          {(result.models.length > 0 || result.threemfs.length > 0) && (
            <div data-testid="scan-library" style={uiText(13, c.textPrimary, { lineHeight: 1.5 })}>
              <Badge tone="green">brought in</Badge>{" "}
              {[result.models.length && plural(result.models.length, "model"), result.threemfs.length && plural(result.threemfs.length, "3MF file")]
                .filter(Boolean)
                .join(" and ")}{" "}
              from the other Farmhand: <span style={{ color: c.textMuted }}>{[...result.models, ...result.threemfs].join(", ")}</span>
            </div>
          )}
          {result.librarySkipped.map((s) => (
            <div key={`lib:${s.name}`} data-testid="scan-library-skipped" style={uiText(13, c.textMuted, { lineHeight: 1.5 })}>
              <Badge tone="muted">left out</Badge> <b style={{ color: c.heading }}>{s.name}</b>: {s.reason}
            </div>
          ))}
          {result.imported.map((p) => (
            <div key={p.projectId} data-testid="scan-imported" style={uiText(13, c.textPrimary, { lineHeight: 1.5 })}>
              <Badge tone="green">{p.repaired ? "rebuilt from its record" : "brought in"}</Badge> <b style={{ color: c.heading }}>{p.name}</b>:{" "}
              {whatsIn(p.files)}
              {p.warnings.map((w) => (
                <div key={w} style={uiText(12, c.amber)}>{w}</div>
              ))}
            </div>
          ))}
          {result.skipped.map((s) => (
            <div key={s.name} data-testid="scan-skipped" style={uiText(13, c.textMuted, { lineHeight: 1.5 })}>
              <Badge tone="muted">left out</Badge> <b style={{ color: c.heading }}>{s.name}</b>: {s.reason}
            </div>
          ))}
        </div>
      )}
      <button data-testid="scan-projects-folder-go" onClick={run} disabled={busy} style={primaryButton(busy)}>
        {busy ? "Scanning…" : "Scan again"}
      </button>
    </div>
  );
}

// Pick the folder the projects are in; each subfolder is listed with what it holds, and the ones ticked are brought in
// one at a time (each a new project named after its folder; the files are copied, the originals left where they are)
function ImportFolders() {
  const { refresh } = useData();
  const [picking, setPicking] = useState(false);
  const [scan, setScan] = useState(null); // { path, folders }
  const [ticked, setTicked] = useState([]); // folder paths to bring in
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(null); // "Importing 2 of 5…"
  const [results, setResults] = useState([]); // [{ name, ok, text, warnings }]
  const [error, setError] = useState(null);

  const load = async (path) => {
    const r = await scanProjectFolder(path); // an error here is shown in the picker
    writeStored(FOLDER_KEY, path);
    setScan(r);
    setTicked(r.folders.filter((f) => !f.inFarmhand && !f.error && f.total > 0).map((f) => f.path));
    setResults([]);
    setError(null);
  };
  const toggle = (path) => setTicked(ticked.includes(path) ? ticked.filter((x) => x !== path) : [...ticked, path]);

  const importTicked = async () => {
    const todo = scan.folders.filter((f) => ticked.includes(f.path));
    setBusy(true);
    setResults([]);
    setError(null);
    const done = [];
    for (const [i, f] of todo.entries()) {
      setProgress(`Importing ${i + 1} of ${todo.length}: ${f.name}…`);
      try {
        const r = await importProjectFolder(f.path);
        done.push({ name: r.name, ok: true, text: `brought in with ${whatsIn(r.files)}.`, warnings: r.warnings });
      } catch (e) {
        done.push({ name: f.name, ok: false, text: errorText(e), warnings: [] });
      }
      setResults([...done]);
    }
    setProgress(null);
    try {
      await refresh();
      await load(scan.path); // marks those brought in as in Farmhand
    } catch (e) {
      setError(errorText(e));
    }
    setResults(done);
    setBusy(false);
  };

  const importable = (f) => !f.inFarmhand && !f.error && f.total > 0;
  return (
    <div data-testid="scan-import">
      <div style={uiText(12, c.textFaint, { lineHeight: 1.6, marginBottom: 12 })}>
        Pick the folder your projects are in. Each folder inside it becomes a project of the same name, with its files
        sorted in: STL and OBJ files (the folders they're in become sub-components), 3MF files (for the printer they
        were sliced for, with a G-code of the same name beside them), CAD files, and everything else as documents. The
        files are copied; the originals stay where they are.
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
        <button data-testid="scan-choose-folder" onClick={() => setPicking(true)} disabled={busy} style={toolButton(12)}>
          <FolderOpen size={12} />
          {scan ? "Another folder…" : "Choose folder…"}
        </button>
        {scan && <span style={monoText(12, c.textMuted, { overflowWrap: "anywhere" })}>{scan.path}</span>}
      </div>

      {scan && (
        <>
          {scan.folders.length === 0 ? (
            <div style={panelBox({ padding: "8px 12px", ...uiText(13, c.textFaint) })}>There are no folders in it.</div>
          ) : (
            <div data-testid="scan-folders" style={panelBox({ maxHeight: "40vh", overflowY: "auto" })}>
              {scan.folders.map((f, i) => (
                <label
                  key={f.path}
                  data-testid="scan-folder"
                  style={{
                    display: "flex", alignItems: "center", gap: 10, padding: "6px 12px", borderTop: i ? `1px solid ${c.border}` : "none",
                    cursor: importable(f) && !busy ? "pointer" : "default",
                  }}
                >
                  <input
                    type="checkbox"
                    checked={ticked.includes(f.path)}
                    disabled={!importable(f) || busy}
                    onChange={() => toggle(f.path)}
                    style={{ accentColor: c.amber }}
                  />
                  <span style={uiText(13, importable(f) ? c.heading : c.textFaint, { overflowWrap: "anywhere" })}>{f.name}</span>
                  <span style={uiText(12, c.textFaint, { marginLeft: "auto", textAlign: "right" })}>{f.error || whatsIn(f.files)}</span>
                  {f.inFarmhand && <Badge>Already in Farmhand</Badge>}
                </label>
              ))}
            </div>
          )}
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 12 }}>
            <span style={uiText(12, c.textMuted)}>{progress}</span>
            <button
              data-testid="scan-import-go"
              onClick={importTicked}
              disabled={busy || ticked.length === 0}
              style={{ ...primaryButton(busy || ticked.length === 0), marginLeft: "auto" }}
            >
              {busy ? "Importing…" : ticked.length ? `Import ${plural(ticked.length, "project")}` : "Import"}
            </button>
          </div>
        </>
      )}

      {error && <div style={uiText(12, c.amber, { marginTop: 10 })}>{error}</div>}
      {results.length > 0 && (
        <div data-testid="scan-results" style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 6 }}>
          {results.map((r) => (
            <div key={r.name} style={uiText(12, r.ok ? c.textMuted : c.amber, { lineHeight: 1.5 })}>
              <b style={{ color: r.ok ? c.green : c.amber }}>{r.name}</b> {r.text}
              {r.warnings.map((w) => (
                <div key={w} style={{ color: c.amber, paddingLeft: 12 }}>
                  {w}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}

      {picking && (
        <FolderPicker
          title="The folder your projects are in"
          startPath={scan?.path || readStored(FOLDER_KEY)}
          onSelect={load}
          onClose={() => setPicking(false)}
        />
      )}
    </div>
  );
}

// Every project file Farmhand keeps, against the disk: missing, or changed outside Farmhand, and files in the project
// files folder no project has on record. Nothing is changed.
function CheckProjects() {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await checkProjectFiles());
    } catch (e) {
      setError(errorText(e));
    }
    setBusy(false);
  };
  // the problems, project by project
  const byProject = [];
  for (const p of result?.problems || []) {
    const group = byProject.find((g) => g.projectId === p.projectId) || byProject[byProject.push({ projectId: p.projectId, project: p.project, items: [] }) - 1];
    group.items.push(p);
  }
  const clean = result && !result.problemsTotal && !result.unknownTotal;
  return (
    <div data-testid="scan-check">
      <div style={uiText(12, c.textFaint, { lineHeight: 1.6, marginBottom: 12 })}>
        Looks at every file your projects keep, to find any that went missing or were changed outside Farmhand, and any
        file in the project files folder that no project has on record. Nothing is changed.
      </div>
      <button data-testid="scan-check-go" onClick={run} disabled={busy} style={primaryButton(busy)}>
        {busy ? "Checking…" : result ? "Check again" : "Check projects"}
      </button>
      {error && <div style={uiText(12, c.amber, { marginTop: 10 })}>{error}</div>}
      {result && (
        <div data-testid="scan-check-result" style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 12 }}>
          {result.error && <div style={uiText(12, c.amber, { lineHeight: 1.5 })}>{result.error}</div>}
          {clean ? (
            <div style={uiText(13, c.green)}>
              All {plural(result.filesChecked, "file")} in {plural(result.projects, "project")} are as Farmhand saved them.
            </div>
          ) : (
            <div style={uiText(12, c.textMuted)}>
              {plural(result.filesChecked, "file")} checked in {plural(result.projects, "project")}.
            </div>
          )}
          {byProject.map((g) => (
            <div key={g.projectId}>
              <div style={uiText(13, c.heading, { fontWeight: 700, marginBottom: 4 })}>{g.project}</div>
              <div style={panelBox({ overflow: "hidden" })}>
                {g.items.map((p, i) => (
                  <div
                    key={`${p.kind}-${p.fileId}-${p.version}-${p.filename}`}
                    data-testid="scan-problem"
                    style={{ display: "flex", gap: 10, padding: "5px 12px", borderTop: i ? `1px solid ${c.border}` : "none", alignItems: "baseline" }}
                  >
                    <span title={p.path} style={monoText(12, c.textPrimary, { overflowWrap: "anywhere" })}>{p.filename}</span>
                    <span style={uiText(12, c.amber, { marginLeft: "auto", textAlign: "right" })}>{p.problem}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
          {result.problemsTotal > result.problems.length && (
            <div style={uiText(12, c.textFaint)}>…and {result.problemsTotal - result.problems.length} more.</div>
          )}
          {result.unknownTotal > 0 && (
            <div>
              <div style={uiText(13, c.heading, { fontWeight: 700, marginBottom: 4 })}>
                Not on record ({result.unknownTotal}): in the project files folder, but no project has them
              </div>
              <div style={panelBox({ maxHeight: 200, overflowY: "auto", padding: "4px 12px" })}>
                {result.unknown.map((path) => (
                  <div key={path} data-testid="scan-unknown" style={monoText(12, c.textMuted, { overflowWrap: "anywhere", padding: "2px 0" })}>
                    {path}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
      <div style={{ ...ui, fontSize: fs(11), color: c.textFaint, marginTop: 14 }}>{result?.root && `Project files folder: ${result.root}`}</div>
    </div>
  );
}
