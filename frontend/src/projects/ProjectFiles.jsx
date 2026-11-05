import { useState } from "react";
import { Box, ChevronDown, FileBox, PenTool, Upload } from "lucide-react";
import { deleteProjectFile, deleteProjectFileVersion, uploadProjectFile, uploadProjectFileVersion } from "../api.js";
import { c } from "../theme.js";
import { useData } from "../data.jsx";
import { useAction } from "../hooks/useAction.js";
import { formatBytes } from "../lib/format.js";
import { ConfirmDialog, DeleteWarning, Modal, ModalActions } from "../components/common/dialogs.jsx";
import { Dropzone, TextField } from "../components/common/fields.jsx";
import { DownloadButton, Thumb, TrashButton } from "../components/common/ui.jsx";
import { monoText, toolButton, uiText } from "../styles.js";

export const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

// "Project only", boxed in purple: on an STL or 3MF a project keeps for itself (uploaded to it, not put in Models)
export function ProjectOnlyTag() {
  return (
    <span
      data-testid="project-only-tag"
      title="Uploaded to this project only: not in Models, and deleted with the project"
      style={uiText(11, c.projectOnly, { border: `1px solid ${c.projectOnly}`, borderRadius: 3, padding: "0 6px", fontWeight: 600, whiteSpace: "nowrap" })}
    >
      Project only
    </span>
  );
}

// A project's own files: its CAD files, and its STLs and 3MFs that aren't in Models. All work alike: a file with versions like
// a 3MF's (the newest shown with its preview, the older ones behind a down arrow), kept in the project files folder.
export const FILE_KINDS = {
  cad: {
    key: "cad", noun: "CAD file", Icon: PenTool, accept: undefined, list: (p) => p.cadFiles,
    drop: "Drop the CAD file here (any kind)", previews: "STEP, IGES, STL, OBJ and Fusion files get a preview.",
  },
  stl: {
    key: "stl", noun: "STL file", Icon: Box, accept: ".stl,.obj", list: (p) => p.stlFiles,
    drop: "Drop the STL (or OBJ) file here", previews: "It gets a preview like an STL in Models.",
  },
  threemf: {
    key: "threemf", noun: "3MF file", Icon: FileBox, accept: ".3mf", list: (p) => p.threemfFiles,
    drop: "Drop the 3MF file here", previews: "Its preview is the picture the slicer saved inside it.",
  },
};

export function FileCard({ project, kind, file, onNewVersion }) {
  const { putProject, printers } = useData();
  const printer = file.printerId != null ? printers.find((p) => p.id === file.printerId) : null;
  const [showOlder, setShowOlder] = useState(false); // older versions start folded away
  const [deleting, setDeleting] = useState(null); // null | "file" | a version
  const [latest, ...older] = file.versions;
  const bodyId = `${kind.key}-versions-${file.id}`;
  return (
    <div data-testid={`${kind.key}-file`} data-file-id={file.id} style={{ border: `1px solid ${c.border}`, borderRadius: 4, overflow: "hidden" }}>
      {/* one slim line; in a narrow window the buttons move onto a second line rather than squeezing the name */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, rowGap: 4, flexWrap: "wrap", padding: "5px 8px 5px 12px", background: c.panelAlt }}>
        <span style={{ display: "flex", alignItems: "center", gap: 8, flex: "1 1 220px", minWidth: 0 }}>
          <kind.Icon size={14} color={c.textFaint} style={{ flexShrink: 0 }} />
          <span
            data-testid={`${kind.key}-name`}
            title={file.name}
            style={monoText(13, c.heading, { minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" })}
          >
            {file.name}
          </span>
          {kind.key !== "cad" && <ProjectOnlyTag />}
        </span>
        {kind.key === "threemf" && (
          <span data-testid="threemf-printer" style={uiText(12, printer ? c.textMuted : c.textFaint, { whiteSpace: "nowrap" })}>
            {printer ? printer.name : "no printer"}
          </span>
        )}
        <span style={uiText(12, c.textFaint, { whiteSpace: "nowrap", marginLeft: kind.key === "threemf" ? 0 : "auto" })}>{plural(file.versions.length, "version")}</span>
        {older.length > 0 && (
          <button
            data-testid={`${kind.key}-versions-toggle`}
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
        <button data-testid={`${kind.key}-new-version`} onClick={onNewVersion} style={toolButton(12, { whiteSpace: "nowrap", flexShrink: 0 })}>
          <Upload size={12} />
          New version
        </button>
        <TrashButton onClick={() => setDeleting("file")} title={`Delete this ${kind.noun}, every version`} />
      </div>
      <FileVersionRow ver={latest} isLatest onDelete={() => setDeleting(latest)} />
      <div id={bodyId}>
        {showOlder && older.map((v) => <FileVersionRow key={v.v} ver={v} onDelete={() => setDeleting(v)} />)}
      </div>
      {deleting && (
        <ConfirmDialog
          title={deleting === "file" ? `Delete ${kind.noun}` : "Delete version"}
          confirmLabel="Delete"
          onClose={() => setDeleting(null)}
          onConfirm={async () =>
            putProject(
              await (deleting === "file"
                ? deleteProjectFile(kind.key, project.id, file.id)
                : deleteProjectFileVersion(kind.key, project.id, file.id, deleting.v))
            )
          }
        >
          {deleting === "file" ? (
            <>
              Delete <strong>{file.name}</strong> and {file.versions.length === 1 ? "its only version" : `all ${file.versions.length} versions`}?
            </>
          ) : (
            <>
              Delete <strong>{deleting.filename}</strong> (v{deleting.v})?
              {file.versions.length === 1 && <DeleteWarning>It's the only version, so the {kind.noun} goes too.</DeleteWarning>}
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
function FileVersionRow({ ver, isLatest = false, onDelete }) {
  return (
    <div
      data-testid="file-version"
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

// The dialog for a new file of this kind (no `file`), or a newer version of one: the file, and a note on what it is or
// what changed. `extra` goes above the note (an STL's "also put it in Models?", a 3MF's printer); `check()` can stop
// the upload with a reason, `fields` adds to what's sent, and `onPicked(file)` hears of the file chosen.
export function UploadDialog({ project, kind, file: existing, onClose, extra, check, fields, onUploaded, onPicked, title }) {
  const { putProject } = useData();
  const [picked, setPickedState] = useState(null);
  const setPicked = (f) => {
    setPickedState(f);
    onPicked?.(f);
  };
  const [note, setNote] = useState("");
  const { busy, error, setError, run } = useAction();
  const submit = () => {
    if (!picked) return setError(`Choose the ${kind.noun} to upload.`);
    const reason = check?.();
    if (reason) return setError(reason);
    run(async () => {
      const out = existing
        ? await uploadProjectFileVersion({ kind: kind.key, projectId: project.id, fileId: existing.id, file: picked, note })
        : await uploadProjectFile({ kind: kind.key, projectId: project.id, file: picked, note, ...fields });
      putProject(out);
      await onUploaded?.();
      onClose();
    });
  };
  const next = existing ? existing.versions[0].v + 1 : 1;
  return (
    <Modal title={title || (existing ? `New version of ${existing.name}` : `Upload ${kind.noun.replace(" file", "")}`)} onClose={onClose}>
      <Dropzone
        label={existing ? `Drop the newer version of the ${kind.noun} here` : kind.drop}
        file={picked}
        onFile={setPicked}
        accept={kind.accept}
      />
      {extra}
      <TextField label="What changed (optional)" value={note} onChange={setNote} placeholder={existing ? "e.g. Wider base" : "e.g. First design"} />
      {(existing || !extra) && (
        <div style={uiText(12, c.textFaint, { marginBottom: 12, lineHeight: 1.5 })}>
          It's kept as version {next} ("name ver {next}") in the project files folder chosen on the Settings page. {kind.previews}
        </div>
      )}
      <ModalActions onClose={onClose} onSubmit={submit} actionLabel="Upload" submitting={busy} errorMsg={error} />
    </Modal>
  );
}
