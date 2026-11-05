import { Fragment, useState } from "react";
import { ChevronDown, ExternalLink, FileBox, Plus, Upload } from "lucide-react";
import { addProjectBundle, bundle3mfUrl, errorText, inspectThreemf, removeProjectBundle } from "../api.js";
import { c, fs, ui } from "../theme.js";
import { useData } from "../data.jsx";
import { useAction } from "../hooks/useAction.js";
import { nameCollator } from "../models/modelSort.js";
import { NewVersionButton } from "../bundles/bundleActions.jsx";
import { GcodeRow } from "../bundles/GcodeRow.jsx";
import { Upload3mfForm } from "../bundles/Upload3mfForm.jsx";
import { ConfirmDialog, Modal } from "../components/common/dialogs.jsx";
import { FieldSelect, SearchBox } from "../components/common/fields.jsx";
import { DownloadButton, Row, Thumb } from "../components/common/ui.jsx";
import { monoText, panelBox, primaryButton, toolButton, uiText } from "../styles.js";
import { FILE_KINDS, FileCard, plural, UploadDialog } from "./ProjectFiles.jsx";

const THREEMF = FILE_KINDS.threemf;

// The 3MF section's buttons: Add existing 3MF, and Upload 3MF
export function ThreemfActions({ onAdd, onUpload }) {
  return (
    <div style={{ display: "flex", gap: 8 }}>
      <button data-testid="threemf-add-existing" onClick={onAdd} style={toolButton(12)}>
        <Plus size={12} />
        Add existing 3MF
      </button>
      <button data-testid="threemf-upload" onClick={onUpload} style={toolButton(12)}>
        <Upload size={12} />
        Upload 3MF
      </button>
    </div>
  );
}

// A project's 3MF files, two kinds, as its STLs: 3MFs from the rest of Farmhand it uses (each is that 3MF, on its
// printer's page and its model's: a new version here is its new version there), and 3MFs uploaded to the project only,
// which belong to it. Either way the printer a 3MF is for comes into the project too.
export function ThreemfFiles({ project, adding, uploading, onCloseAdd, onCloseUpload, onOpenPrinter }) {
  const { bundles } = useData();
  const [newVersionOf, setNewVersionOf] = useState(null);
  const used = project.bundleIds.map((id) => bundles.find((b) => b.id === id)).filter(Boolean);
  const count = used.length + project.threemfFiles.length;
  return (
    <>
      {count === 0 ? (
        <div style={panelBox({ padding: "7px 12px", ...uiText(13, c.textFaint, { lineHeight: 1.5 }) })}>
          No 3MF files yet. <b style={{ color: c.textMuted }}>Add existing 3MF</b> uses one already in Farmhand;{" "}
          <b style={{ color: c.textMuted }}>Upload 3MF</b> adds a new one. Its printer comes into the project too.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {used.map((b) => (
            <BundleLinkCard key={`b${b.id}`} project={project} bundle={b} onOpenPrinter={() => onOpenPrinter(b.printerId)} />
          ))}
          {project.threemfFiles.map((f) => (
            <FileCard key={`f${f.id}`} project={project} kind={THREEMF} file={f} onNewVersion={() => setNewVersionOf(f)} />
          ))}
        </div>
      )}
      {adding && <AddExisting project={project} onClose={onCloseAdd} />}
      {uploading && <UploadThreemf project={project} onClose={onCloseUpload} />}
      {newVersionOf && <UploadDialog project={project} kind={THREEMF} file={newVersionOf} onClose={() => setNewVersionOf(null)} />}
    </>
  );
}

// A 3MF from the rest of Farmhand in the project: its name, "In Models", its printer and STLs, its newest version (the
// older ones behind the down arrow) with its G-code (Download, Send to the printer), and New version, Open on its
// printer's page and Take out. It IS that 3MF: a new version here is its new version everywhere.
function BundleLinkCard({ project, bundle: b, onOpenPrinter }) {
  const { putProject, printers, bundleTitle } = useData();
  const [asking, setAsking] = useState(false);
  const [showOlder, setShowOlder] = useState(false);
  const [latest, ...older] = b.versions;
  const printer = printers.find((p) => p.id === b.printerId);
  const row = (v, isLatest) => (
    <Fragment key={v.v}>
      <div data-testid="threemf-bundle-version" data-version={v.v} style={{ display: "flex", alignItems: "center", gap: 14, padding: "10px 16px", borderTop: `1px solid ${c.border}`, flexWrap: "wrap" }}>
        <Thumb src={v.thumb} size={64} plateGrid placeholderIcon />
        <span style={monoText(12, isLatest ? c.amber : c.textFaint, { width: 30 })}>v{v.v}</span>
        <div style={{ flex: "1 1 220px", minWidth: 0 }}>
          <div style={monoText(12, c.textPrimary, { overflowWrap: "anywhere" })}>{v.filename}</div>
          <div style={uiText(12, c.textFaint, { marginTop: 3 })}>{[v.date, v.note].filter(Boolean).join(" · ")}</div>
        </div>
        <div style={{ marginLeft: "auto" }}>
          <DownloadButton disabled={!v.full} href={bundle3mfUrl(v.id)} />
        </div>
      </div>
      {v.gcodeName && <GcodeRow ver={v} bundle={b} />}
    </Fragment>
  );
  return (
    <div data-testid="threemf-bundle" data-bundle-id={b.id} style={{ border: `1px solid ${c.border}`, borderRadius: 4, overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, rowGap: 4, flexWrap: "wrap", padding: "5px 8px 5px 12px", background: c.panelAlt }}>
        <span style={{ display: "flex", alignItems: "center", gap: 8, flex: "1 1 220px", minWidth: 0 }}>
          <FileBox size={14} color={c.textFaint} style={{ flexShrink: 0 }} />
          <span title={b.name} style={monoText(13, c.heading, { minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" })}>
            {b.name}
          </span>
          <span
            title="This is the 3MF on its printer's and its model's pages: a new version here is its new version there too"
            style={uiText(11, c.textMuted, { border: `1px solid ${c.borderStrong}`, borderRadius: 3, padding: "0 6px", whiteSpace: "nowrap" })}
          >
            In Models
          </span>
        </span>
        <span title={bundleTitle(b) ? `From ${bundleTitle(b)}` : undefined} style={uiText(12, c.textMuted, { whiteSpace: "nowrap", marginLeft: "auto" })}>
          {printer?.name || "?"}
        </span>
        <span style={uiText(12, c.textFaint, { whiteSpace: "nowrap" })}>{plural(b.versions.length, "version")}</span>
        {older.length > 0 && (
          <button
            data-testid="threemf-bundle-versions-toggle"
            aria-expanded={showOlder}
            onClick={() => setShowOlder(!showOlder)}
            title={showOlder ? `Hide ${plural(older.length, "older version")}` : `Show ${plural(older.length, "older version")}`}
            style={toolButton(12, { whiteSpace: "nowrap" })}
          >
            <ChevronDown size={12} style={{ transform: showOlder ? "rotate(180deg)" : "none", transition: "transform 0.12s ease" }} />
            {older.length} older
          </button>
        )}
        <NewVersionButton bundle={b} />
        <button data-testid="threemf-open-printer" onClick={onOpenPrinter} title="Open it on its printer's page" style={toolButton(12, { whiteSpace: "nowrap" })}>
          <ExternalLink size={12} />
          Open
        </button>
        <button data-testid="threemf-take-out" onClick={() => setAsking(true)} title="Take it out of this project" style={toolButton(12, { whiteSpace: "nowrap" })}>
          Take out
        </button>
      </div>
      {latest && row(latest, true)}
      {showOlder && older.map((v) => row(v, false))}
      {asking && (
        <ConfirmDialog
          title="Take out of project"
          confirmLabel="Take it out"
          tone="warn"
          onClose={() => setAsking(false)}
          onConfirm={async () => putProject(await removeProjectBundle(project.id, b.id))}
        >
          Take <strong>{b.name}</strong> out of {project.name}? It stays in Farmhand, and its printer stays in the project:
          nothing is deleted.
        </ConfirmDialog>
      )}
    </div>
  );
}

// Picking 3MFs already in Farmhand: every one not in the project yet, searchable by its name, printer or STLs. Each is
// added at once (its printer with it), and the dialog stays open for the next.
function AddExisting({ project, onClose }) {
  const { bundles, printers, bundleTitle, putProject } = useData();
  const [query, setQuery] = useState("");
  const { busy, error, run } = useAction();
  const inProject = new Set(project.bundleIds);
  const printerName = (id) => printers.find((p) => p.id === id)?.name || "?";
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const choices = bundles
    .filter((b) => !inProject.has(b.id))
    .filter((b) => words.every((w) => `${b.name} ${printerName(b.printerId)} ${bundleTitle(b)}`.toLowerCase().includes(w)))
    .sort((a, b) => nameCollator.compare(a.name, b.name));
  return (
    <Modal title={`Add 3MF files to ${project.name}`} onClose={onClose} width={600}>
      <SearchBox value={query} onChange={setQuery} placeholder="Search 3MF files, printers, STLs…" label="Search 3MF files" style={{ marginBottom: 12 }} />
      {error && <div style={uiText(12, c.amber, { marginBottom: 10 })}>{error}</div>}
      <div style={panelBox({ overflow: "hidden", maxHeight: "50vh", overflowY: "auto" })}>
        {choices.length === 0 ? (
          <div style={{ padding: 16, ...uiText(13, c.textFaint) }}>
            {bundles.length === inProject.size ? "Every 3MF in Farmhand is in this project already." : "No 3MF files match."}
          </div>
        ) : (
          choices.map((b) => (
            <Row key={b.id} hoverable={false}>
              <Thumb src={b.versions[0]?.thumb} size={36} plateGrid placeholderIcon />
              <div style={{ flex: 1, minWidth: 0, marginLeft: 12 }}>
                <div style={monoText(12, c.textPrimary, { overflowWrap: "anywhere" })}>{b.name}</div>
                <div style={uiText(12, c.textFaint, { marginTop: 2 })}>
                  {printerName(b.printerId)} · {bundleTitle(b) || "no STL"}
                </div>
              </div>
              <button
                disabled={busy}
                data-testid={`threemf-pick-${b.id}`}
                onClick={() => run(async () => putProject(await addProjectBundle(project.id, b.id)))}
                style={{ ...primaryButton(busy), fontSize: fs(12), padding: "5px 12px", marginLeft: 12, ...ui }}
              >
                Add
              </button>
            </Row>
          ))
        )}
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 12 }}>
        <button onClick={onClose} style={toolButton(13)}>
          Done
        </button>
      </div>
    </Modal>
  );
}

// Upload 3MF asks first: also put it in Models? Yes: the usual 3MF upload (its STL, its printer read from the file),
// then the project uses it. No: it's uploaded to the project only, with the printer it's for.
function UploadThreemf({ project, onClose }) {
  const { putProject } = useData();
  const [choice, setChoice] = useState(null); // null | "models" | "project"
  if (choice === "models") {
    return (
      <Modal title="Upload 3MF (to Models too)" onClose={onClose}>
        <Upload3mfForm onClose={onClose} onUploaded={async (out) => putProject(await addProjectBundle(project.id, out.id))} />
      </Modal>
    );
  }
  if (choice === "project") return <UploadProjectThreemf project={project} onClose={onClose} />;
  const option = (value, title, detail) => (
    <button
      data-testid={`threemf-in-models-${value === "models" ? "yes" : "no"}`}
      onClick={() => setChoice(value)}
      style={{ ...ui, display: "block", width: "100%", textAlign: "left", background: c.panelAlt, border: `1px solid ${c.border}`, borderRadius: 4, padding: 12, marginBottom: 10, cursor: "pointer", color: c.heading, fontSize: fs(13) }}
    >
      {title}
      <span style={{ display: "block", color: c.textFaint, fontSize: fs(12), marginTop: 3, lineHeight: 1.5 }}>{detail}</span>
    </button>
  );
  return (
    <Modal title="Upload 3MF" onClose={onClose}>
      <div style={uiText(13, c.heading, { marginBottom: 10 })}>Also put it in Models?</div>
      {option("models", "Yes, put it in Models too", "The usual 3MF upload: pick its STL, and its printer is read from the file. It shows on the Models and Printers pages, and this project uses it.")}
      {option("project", "No, keep it in this project only", "It belongs to this project: kept in the project files folder, with versions, and deleted with the project.")}
      <div style={uiText(12, c.textFaint, { lineHeight: 1.5 })}>Either way, the printer it's for comes into the project too.</div>
    </Modal>
  );
}

// A 3MF for the project only: the file, the printer it's for (suggested from the file's own printer profile), a note
function UploadProjectThreemf({ project, onClose }) {
  const { printers } = useData();
  const [printerId, setPrinterId] = useState("");
  const [reading, setReading] = useState(null); // what the file says about its printer, once read
  const choices = printers.filter((p) => !p.decommissioned).map((p) => ({ value: String(p.id), label: p.name }));
  const onPicked = async (file) => {
    setReading(file ? { busy: true } : null);
    if (!file) return;
    try {
      const r = await inspectThreemf(file);
      setReading({ profile: r.printerProfileName, matched: r.matchedPrinter });
      if (r.matchedPrinter) setPrinterId(String(r.matchedPrinter.id));
    } catch (e) {
      setReading({ error: errorText(e) });
    }
  };
  return (
    <UploadDialog
      project={project}
      kind={THREEMF}
      title="Upload 3MF to this project only"
      onClose={onClose}
      onPicked={onPicked}
      check={() => (printerId ? null : "Pick the printer this 3MF is for.")}
      fields={{ printerId: printerId ? Number(printerId) : null }}
      extra={
        <div data-testid="threemf-printer-choice">
          <FieldSelect label="Printer it's for (it comes into the project too)" placeholder="Select a printer…" value={printerId} onChange={setPrinterId} options={choices} />
          {reading && (
            <div style={uiText(12, reading.error ? c.amber : c.textFaint, { marginTop: -8, marginBottom: 12, lineHeight: 1.5 })}>
              {reading.busy
                ? "Reading the 3MF…"
                : reading.error
                  ? `Couldn't read the 3MF: ${reading.error}`
                  : reading.matched
                    ? `Picked ${reading.matched.name}: the printer this file was sliced for.`
                    : reading.profile
                      ? `It was sliced for "${reading.profile}", which isn't a printer here: pick the one it's for.`
                      : "The file doesn't say which printer it's for: pick it."}
            </div>
          )}
        </div>
      }
    />
  );
}
