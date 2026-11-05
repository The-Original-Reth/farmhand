import { useState } from "react";
import { ChevronDown, PenTool, Upload } from "lucide-react";
import { deleteCadFile, deleteCadVersion, uploadCad, uploadCadVersion } from "../api.js";
import { c } from "../theme.js";
import { useData } from "../data.jsx";
import { useAction } from "../hooks/useAction.js";
import { formatBytes } from "../lib/format.js";
import { ConfirmDialog, DeleteWarning, Modal, ModalActions } from "../components/common/dialogs.jsx";
import { Dropzone, TextField } from "../components/common/fields.jsx";
import { DownloadButton, Thumb, TrashButton } from "../components/common/ui.jsx";
import { monoText, panelBox, toolButton, uiText } from "../styles.js";

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

// The project's CAD files, any kind (Fusion, STEP, SolidWorks...), each with its versions like a 3MF's: the newest
// shown with its preview, the older ones behind a down arrow. `upload`: show the Upload CAD dialog (the section's
// heading has the button). Kept in the project files folder chosen on the Settings page.
export function CadFiles({ project, uploading, onCloseUpload }) {
  const [newVersionOf, setNewVersionOf] = useState(null); // a CAD file a newer version is being uploaded for
  return (
    <>
      {project.cadFiles.length === 0 ? (
        <div style={panelBox({ padding: "7px 12px", ...uiText(13, c.textFaint, { lineHeight: 1.5 }) })}>
          No CAD files yet. <b style={{ color: c.textMuted }}>Upload CAD</b> adds one of any kind (Fusion, STEP, IGES,
          SolidWorks, OpenSCAD...); each newer version is kept, and every version can be downloaded.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {project.cadFiles.map((cad) => (
            <CadCard key={cad.id} project={project} cad={cad} onNewVersion={() => setNewVersionOf(cad)} />
          ))}
        </div>
      )}
      {(uploading || newVersionOf) && (
        <Modal
          title={newVersionOf ? `New version of ${newVersionOf.name}` : "Upload CAD file"}
          onClose={() => (newVersionOf ? setNewVersionOf(null) : onCloseUpload())}
        >
          <CadUploadForm project={project} cad={newVersionOf} onClose={() => (newVersionOf ? setNewVersionOf(null) : onCloseUpload())} />
        </Modal>
      )}
    </>
  );
}

export function UploadCadButton({ onClick }) {
  return (
    <button data-testid="cad-upload" onClick={onClick} style={toolButton(12)}>
      <Upload size={12} />
      Upload CAD
    </button>
  );
}

function CadCard({ project, cad, onNewVersion }) {
  const { putProject } = useData();
  const [showOlder, setShowOlder] = useState(false); // older versions start folded away
  const [deleting, setDeleting] = useState(null); // null | "file" | a version
  const [latest, ...older] = cad.versions;
  const bodyId = `cad-versions-${cad.id}`;
  return (
    <div data-testid="cad-file" data-cad-id={cad.id} style={{ border: `1px solid ${c.border}`, borderRadius: 4, overflow: "hidden" }}>
      {/* one slim line; in a narrow window the buttons move onto a second line rather than squeezing the name */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, rowGap: 4, flexWrap: "wrap", padding: "5px 8px 5px 12px", background: c.panelAlt }}>
        <span style={{ display: "flex", alignItems: "center", gap: 8, flex: "1 1 220px", minWidth: 0 }}>
          <PenTool size={14} color={c.textFaint} style={{ flexShrink: 0 }} />
          <span
            data-testid="cad-name"
            title={cad.name}
            style={monoText(13, c.heading, { minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" })}
          >
            {cad.name}
          </span>
        </span>
        <span style={uiText(12, c.textFaint, { whiteSpace: "nowrap", marginLeft: "auto" })}>{plural(cad.versions.length, "version")}</span>
        {older.length > 0 && (
          <button
            data-testid="cad-versions-toggle"
            aria-expanded={showOlder}
            aria-controls={bodyId}
            onClick={() => setShowOlder(!showOlder)}
            title={showOlder ? `Hide ${plural(older.length, "older version")}` : `Show ${plural(older.length, "older version")}`}
            style={toolButton(12, { whiteSpace: "nowrap", flexShrink: 0 })}
          >
            <ChevronDown size={12} style={{ transform: showOlder ? "rotate(180deg)" : "none", transition: "transform 0.12s ease" }} />
            {older.length} older
          </button>
        )}
        <button data-testid="cad-new-version" onClick={onNewVersion} style={toolButton(12, { whiteSpace: "nowrap", flexShrink: 0 })}>
          <Upload size={12} />
          New version
        </button>
        <TrashButton onClick={() => setDeleting("file")} title="Delete this CAD file, every version" />
      </div>
      <CadVersionRow ver={latest} isLatest onDelete={() => setDeleting(latest)} />
      <div id={bodyId}>
        {showOlder && older.map((v) => <CadVersionRow key={v.v} ver={v} onDelete={() => setDeleting(v)} />)}
      </div>
      {deleting && (
        <ConfirmDialog
          title={deleting === "file" ? "Delete CAD file" : "Delete version"}
          confirmLabel="Delete"
          onClose={() => setDeleting(null)}
          onConfirm={async () =>
            putProject(
              await (deleting === "file" ? deleteCadFile(project.id, cad.id) : deleteCadVersion(project.id, cad.id, deleting.v))
            )
          }
        >
          {deleting === "file" ? (
            <>
              Delete <strong>{cad.name}</strong> and {cad.versions.length === 1 ? "its only version" : `all ${cad.versions.length} versions`}?
            </>
          ) : (
            <>
              Delete <strong>{deleting.filename}</strong> (v{deleting.v})?
              {cad.versions.length === 1 && <DeleteWarning>It's the only version, so the CAD file goes too.</DeleteWarning>}
            </>
          )}
          <DeleteWarning>The {deleting === "file" ? "files are" : "file is"} deleted for good.</DeleteWarning>
        </ConfirmDialog>
      )}
    </div>
  );
}

// One version: its preview (drawn like an STL's where the file allows), number, date, size, what changed, and
// Download and delete
function CadVersionRow({ ver, isLatest = false, onDelete }) {
  return (
    <div
      data-testid="cad-version"
      data-version={ver.v}
      style={{ display: "flex", alignItems: "center", gap: 14, padding: "10px 16px", borderTop: `1px solid ${c.border}`, flexWrap: "wrap" }}
    >
      <a href={ver.preview || undefined} target="_blank" rel="noreferrer" title={ver.preview ? "Open the preview" : "No preview for this kind of file"}>
        <Thumb src={ver.preview} size={64} background="#FFFFFF" placeholderIcon />
      </a>
      <span style={monoText(12, isLatest ? c.amber : c.textFaint, { width: 30 })}>v{ver.v}</span>
      <div style={{ flex: "1 1 220px", minWidth: 0 }}>
        <div style={monoText(12, c.textPrimary, { overflowWrap: "anywhere" })}>{ver.filename}</div>
        <div style={uiText(12, c.textFaint, { marginTop: 3 })}>
          {[ver.date, formatBytes(ver.size), ver.note].filter(Boolean).join(" · ")}
        </div>
      </div>
      <div style={{ display: "flex", gap: 8, marginLeft: "auto" }}>
        <DownloadButton href={ver.download} />
        <TrashButton onClick={onDelete} title="Delete this version" />
      </div>
    </div>
  );
}

// A new CAD file (no `cad`), or a newer version of one: the file, and a note on what it is or what changed
function CadUploadForm({ project, cad, onClose }) {
  const { putProject } = useData();
  const [file, setFile] = useState(null);
  const [note, setNote] = useState("");
  const { busy, error, setError, run } = useAction();
  const submit = () => {
    if (!file) return setError("Choose the CAD file to upload.");
    run(async () => {
      putProject(
        await (cad
          ? uploadCadVersion({ projectId: project.id, cadId: cad.id, file, note })
          : uploadCad({ projectId: project.id, file, note }))
      );
      onClose();
    });
  };
  const next = cad ? cad.versions[0].v + 1 : 1;
  return (
    <div>
      <Dropzone label={cad ? "Drop the newer version of the CAD file here" : "Drop the CAD file here (any kind)"} file={file} onFile={setFile} />
      <TextField label="What changed (optional)" value={note} onChange={setNote} placeholder={cad ? "e.g. Wider base" : "e.g. First design"} />
      <div style={uiText(12, c.textFaint, { marginBottom: 12, lineHeight: 1.5 })}>
        It's kept as version {next} ("name ver {next}") in the project files folder chosen on the Settings page. STEP, IGES,
        STL, OBJ and Fusion files get a preview.
      </div>
      <ModalActions onClose={onClose} onSubmit={submit} actionLabel="Upload" submitting={busy} errorMsg={error} />
    </div>
  );
}
