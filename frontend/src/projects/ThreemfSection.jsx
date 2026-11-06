import { Fragment, useState } from "react";
import { ExternalLink, FileBox, FileCode, Plus, Upload } from "lucide-react";
import { addProjectBundle, bundle3mfUrl, errorText, inspectThreemf, removeProjectBundle } from "../api.js";
import { c, fs, ui } from "../theme.js";
import { useData } from "../data.jsx";
import { NewVersionButton } from "../bundles/bundleActions.jsx";
import { GcodeRow } from "../bundles/GcodeRow.jsx";
import { Upload3mfForm } from "../bundles/Upload3mfForm.jsx";
import { UploadGcodeForm } from "../bundles/UploadGcodeForm.jsx";
import { Modal } from "../components/common/dialogs.jsx";
import { FieldSelect } from "../components/common/fields.jsx";
import { DownloadButton } from "../components/common/ui.jsx";
import { toolButton, uiText } from "../styles.js";
import { FILE_KINDS, FileCard, UploadDialog } from "./ProjectFiles.jsx";
import { Card, CardTitle, EmptyBox, HeadingButton, InModelsTag, OlderToggle, PickDialog, plural, TakeOutButton, VersionLine } from "./pieces.jsx";

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
  return (
    <>
      {used.length + project.threemfFiles.length === 0 ? (
        <EmptyBox>
          No 3MF files yet. <b style={{ color: c.textMuted }}>Add existing 3MF</b> uses one already in Farmhand;{" "}
          <b style={{ color: c.textMuted }}>Upload 3MF</b> adds a new one. Its printer comes into the project too.
        </EmptyBox>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {used.map((b) => (
            <BundleCard key={`b${b.id}`} project={project} bundle={b} onOpenPrinter={() => onOpenPrinter(b.printerId)} />
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
// older ones behind the down arrow) with its G-code (Download, Send to the printer), and Upload G-code, New version,
// Open on its printer's page and Take out. It IS that 3MF: a new version here is its new version everywhere.
function BundleCard({ project, bundle: b, onOpenPrinter }) {
  const { putProject, printers, bundleTitle } = useData();
  const [showOlder, setShowOlder] = useState(false);
  const [uploadingGcode, setUploadingGcode] = useState(false);
  const [latest, ...older] = b.versions;
  const printer = printers.find((p) => p.id === b.printerId);
  const line = (v, isLatest) => (
    <Fragment key={v.v}>
      <VersionLine
        testId="threemf-bundle-version"
        ver={v}
        isLatest={isLatest}
        thumb={v.thumb}
        plateGrid
        filename={v.filename}
        details={[v.date, v.note].filter(Boolean).join(" · ")}
      >
        <DownloadButton disabled={!v.full} href={bundle3mfUrl(v.id)} />
      </VersionLine>
      {v.gcodeName && <GcodeRow ver={v} bundle={b} />}
    </Fragment>
  );
  return (
    <Card
      testId="threemf-bundle"
      dataAttrs={{ "data-bundle-id": b.id }}
      heading={
        <>
          <CardTitle
            Icon={FileBox}
            name={b.name}
            tags={<InModelsTag title="This is the 3MF on its printer's and its model's pages: a new version here is its new version there too" />}
          />
          <span title={bundleTitle(b) ? `From ${bundleTitle(b)}` : undefined} style={uiText(12, c.textMuted, { whiteSpace: "nowrap", marginLeft: "auto" })}>
            {printer?.name || "?"}
          </span>
          <span style={uiText(12, c.textFaint, { whiteSpace: "nowrap" })}>{plural(b.versions.length, "version")}</span>
          <OlderToggle count={older.length} open={showOlder} onToggle={() => setShowOlder(!showOlder)} testId="threemf-bundle-versions-toggle" />
          <HeadingButton
            testId="threemf-bundle-gcode-upload"
            Icon={FileCode}
            label={latest?.gcodeName ? "Replace G-code" : "Upload G-code"}
            title={latest?.gcodeName ? "Upload a newer G-code for its newest version" : "Upload the G-code sliced from its newest version"}
            onClick={() => setUploadingGcode(true)}
          />
          <NewVersionButton bundle={b} />
          <HeadingButton testId="threemf-open-printer" Icon={ExternalLink} label="Open" title="Open it on its printer's page" onClick={onOpenPrinter} />
          <TakeOutButton testId="threemf-take-out" onConfirm={async () => putProject(await removeProjectBundle(project.id, b.id))}>
            Take <strong>{b.name}</strong> out of {project.name}? It stays in Farmhand, and its printer stays in the project:
            nothing is deleted.
          </TakeOutButton>
        </>
      }
    >
      {latest && line(latest, true)}
      {showOlder && older.map((v) => line(v, false))}
      {uploadingGcode && (
        <Modal title={`G-code for ${b.name}`} onClose={() => setUploadingGcode(false)}>
          <UploadGcodeForm bundles={[b]} onClose={() => setUploadingGcode(false)} />
        </Modal>
      )}
    </Card>
  );
}

// Picking 3MFs already in Farmhand: every one not in the project yet, searchable by its name, printer or STLs (its
// printer comes with it)
function AddExisting({ project, onClose }) {
  const { bundles, printers, bundleTitle } = useData();
  const printerName = (id) => printers.find((p) => p.id === id)?.name || "?";
  const items = bundles
    .filter((b) => !project.bundleIds.includes(b.id))
    .map((b) => ({
      id: b.id,
      name: b.name,
      sub: `${printerName(b.printerId)} · ${bundleTitle(b) || "no STL"}`,
      search: `${b.name} ${printerName(b.printerId)} ${bundleTitle(b)}`,
      thumb: b.versions[0]?.thumb,
      plateGrid: true,
      mono: true,
    }));
  return (
    <PickDialog
      title={`Add 3MF files to ${project.name}`}
      width={600}
      noun="3MF files"
      searchPlaceholder="Search 3MF files, printers, STLs…"
      items={items}
      allTaken="Every 3MF in Farmhand is in this project already."
      add={(id) => addProjectBundle(project.id, id)}
      pickTestId="threemf-pick"
      onClose={onClose}
    />
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

// 3MFs for the project only: the files (one or several), the printer each is for, a note. Each file is read for the
// printer it was sliced for; one that's a printer here goes to it, and the printer picked is for the rest. With one
// file, the printer it names is simply picked (and can be changed).
function UploadProjectThreemf({ project, onClose }) {
  const { printers } = useData();
  const [printerId, setPrinterId] = useState("");
  const [read, setRead] = useState(null); // null | { busy } | { files: [{ file, profile, matched, error }] }
  const choices = printers.filter((p) => !p.decommissioned).map((p) => ({ value: String(p.id), label: p.name }));
  const onPicked = async (picked) => {
    const files = picked || [];
    setRead(files.length ? { busy: true } : null);
    if (!files.length) return;
    const results = await Promise.all(
      files.map((file) =>
        inspectThreemf(file).then(
          (r) => ({ file, profile: r.printerProfileName, matched: r.matchedPrinter }),
          (e) => ({ file, error: errorText(e) }),
        ),
      ),
    );
    setRead({ files: results });
    if (results.length === 1 && results[0].matched) setPrinterId(String(results[0].matched.id));
  };
  const single = read?.files?.length === 1;
  const own = (f) => (single ? null : read?.files?.find((x) => x.file === f)?.matched); // a file's own printer, with several
  const rest = read?.files ? read.files.filter((x) => !own(x.file)) : []; // the files the printer picked is for
  const need = !read?.files || rest.length > 0;
  return (
    <UploadDialog
      project={project}
      kind={THREEMF}
      title="Upload 3MF to this project only"
      onClose={onClose}
      onPicked={onPicked}
      check={() => (read?.busy ? "Still reading the 3MF files…" : need && !printerId ? `Pick the printer ${single || !read ? "this 3MF is" : "they're"} for.` : null)}
      fieldsFor={(f) => ({ printerId: own(f)?.id ?? (printerId ? Number(printerId) : null) })}
      extra={
        <div data-testid="threemf-printer-choice">
          {need && (
            <FieldSelect
              label={read?.files && !single && rest.length < read.files.length ? `Printer for the ${plural(rest.length, "other file")} (it comes into the project too)` : "Printer it's for (it comes into the project too)"}
              placeholder="Select a printer…"
              value={printerId}
              onChange={setPrinterId}
              options={choices}
            />
          )}
          {read && (
            <div data-testid="threemf-printer-read" style={uiText(12, c.textFaint, { marginTop: need ? -8 : 0, marginBottom: 12, lineHeight: 1.5 })}>
              {read.busy ? "Reading the 3MF…" : single ? <OneRead r={read.files[0]} /> : <ManyRead files={read.files} />}
            </div>
          )}
        </div>
      }
    />
  );
}

// What one 3MF says about its printer
function OneRead({ r }) {
  if (r.error) return <span style={{ color: c.amber }}>Couldn't read the 3MF: {r.error}</span>;
  if (r.matched) return `Picked ${r.matched.name}: the printer this file was sliced for.`;
  if (r.profile) return `It was sliced for "${r.profile}", which isn't a printer here: pick the one it's for.`;
  return "The file doesn't say which printer it's for: pick it.";
}

// Which printer each of several 3MFs goes to: its own, or the one picked
function ManyRead({ files }) {
  return (
    <>
      {files.some((r) => r.matched)
        ? "Each goes to the printer it was sliced for; the printer picked is for the rest."
        : "None of them names a printer here, so they all go to the printer picked."}
      <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
        {files.map((r, i) => (
          <li key={i} style={{ overflowWrap: "anywhere" }}>
            <span style={{ color: c.textMuted }}>{r.file.name}</span>:{" "}
            {r.matched ? (
              r.matched.name
            ) : r.error ? (
              <span style={{ color: c.amber }}>couldn't be read ({r.error}), so the printer picked</span>
            ) : r.profile ? (
              `sliced for "${r.profile}", not a printer here, so the printer picked`
            ) : (
              "doesn't say, so the printer picked"
            )}
          </li>
        ))}
      </ul>
    </>
  );
}
