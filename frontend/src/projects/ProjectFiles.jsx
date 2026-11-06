import { useState } from "react";
import { Box, FileBox, FileCode, FileText, PenTool, Send, Upload } from "lucide-react";
import {
  deleteProjectFile, deleteProjectFileVersion, errorText, sendProjectGcode, setProjectStlCounts, uploadProjectFile,
  uploadProjectFileVersion, uploadProjectGcode,
} from "../api.js";
import { c, fs } from "../theme.js";
import { useData } from "../data.jsx";
import { useAction } from "../hooks/useAction.js";
import { formatBytes } from "../lib/format.js";
import { ConfirmDialog, DeleteWarning, Modal, ModalActions } from "../components/common/dialogs.jsx";
import { Dropzone, TextField } from "../components/common/fields.jsx";
import { DownloadButton, Thumb, TrashButton } from "../components/common/ui.jsx";
import { fieldBox, headerButton, monoText, uiText } from "../styles.js";
import { Card, CardTitle, HeadingButton, MoveButton, nameStyle, OlderToggle, plural, ProjectOnlyTag } from "./pieces.jsx";

// How many: "have / need", changed right there (each saved when the box is left or Enter is pressed; one out of range
// goes back). Amber while there are fewer than needed, green once there are enough. `onSave({ have })` or
// `onSave({ need })` saves one (it answers the project). needFixed: need is only shown (a BOM part's is changed with
// its Edit button).
export function HaveNeed({ have, need, onSave, label = "", needFixed = false }) {
  const done = have >= need;
  return (
    <span
      data-testid="have-need"
      title={done ? "There are enough" : `${need - have} more needed`}
      style={{ display: "inline-flex", alignItems: "center", gap: 4, whiteSpace: "nowrap" }}
    >
      <CountBox value={have} least={0} onSave={(n) => onSave({ have: n })} color={done ? c.green : c.amber} label={`How many ${label} you have`} testId="have" />
      <span style={uiText(13, c.textFaint)}>/</span>
      {needFixed ? (
        <span data-testid="need" title={`How many ${label} are needed (change it with Edit)`} style={monoText(13, c.textPrimary, { width: NEED_FIXED_WIDTH, textAlign: "center" })}>
          {need}
        </span>
      ) : (
        <CountBox value={need} least={1} onSave={(n) => onSave({ need: n })} color={c.textPrimary} label={`How many ${label} are needed`} testId="need" />
      )}
    </span>
  );
}

// "Have" and "Need", under a section's heading, lined up over the HaveNeed at the start of each row below it
// (needFixed: over a need that's only shown, as a BOM part's)
export function HaveNeedLabel({ needFixed = false, testId }) {
  const cell = (text, width) => (
    <span style={{ width, display: "flex", justifyContent: "center", whiteSpace: "nowrap", ...uiText(11, c.textFaint) }}>{text}</span>
  );
  return (
    <div data-testid={testId} style={{ display: "flex", alignItems: "center", gap: 4, paddingLeft: 13 }}>
      {cell("Have", 58)}
      <span style={uiText(13, c.textFaint, { visibility: "hidden" })}>/</span>
      {cell("Need", needFixed ? NEED_FIXED_WIDTH : 58)}
    </div>
  );
}

const NEED_FIXED_WIDTH = 34; // a need that's only shown, so the column lines up from row to row

function CountBox({ value, least, onSave, color, label, testId }) {
  const { putProject } = useData();
  const [text, setText] = useState(String(value));
  const [shownFor, setShownFor] = useState(value);
  const { busy, error, run } = useAction();
  if (shownFor !== value) {
    // the saved number changed (here or elsewhere): show it
    setShownFor(value);
    setText(String(value));
  }
  const save = () => {
    const n = Number(text);
    if (!Number.isInteger(n) || n < least) return setText(String(value));
    if (n !== value) run(async () => putProject(await onSave(n)));
  };
  return (
    <input
      type="number"
      min={least}
      value={text}
      disabled={busy}
      aria-label={label}
      title={error || label}
      data-testid={testId}
      onChange={(e) => setText(e.target.value)}
      onBlur={save}
      onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
      onClick={(e) => e.stopPropagation()}
      style={{ ...fieldBox(), width: 58, padding: "3px 6px", fontSize: fs(13), color, borderColor: error ? c.danger : c.border }}
    />
  );
}

// A project's own files: its documents and CAD files, and its STLs and 3MFs that aren't in Models. All work alike: a file with versions like
// a 3MF's (the newest shown with its preview, the older ones behind a down arrow), kept in the project files folder.
// opens: clicking a file's name opens it in a new tab; multiple: several can be uploaded at once
export const FILE_KINDS = {
  doc: {
    opens: true,
    multiple: true,
    key: "doc", noun: "document", Icon: FileText, accept: undefined, list: (p) => p.docFiles, noteLabel: "Notes (optional)",
    drop: "Drop the files here (any kind): one or several", previews: "Pictures get a preview.",
  },
  cad: {
    key: "cad", noun: "CAD file", Icon: PenTool, accept: undefined, list: (p) => p.cadFiles,
    drop: "Drop the CAD file here (any kind)", previews: "STEP, IGES, STL, OBJ and Fusion files get a preview.",
  },
  stl: {
    key: "stl", noun: "STL file", Icon: Box, accept: ".stl,.obj", list: (p) => p.stlFiles,
    drop: "Drop STL (or OBJ) files here: one, several, or a folder of them", previews: "It gets a preview like an STL in Models.",
  },
  threemf: {
    multiple: true,
    key: "threemf", noun: "3MF file", Icon: FileBox, accept: ".3mf", list: (p) => p.threemfFiles,
    drop: "Drop the 3MF files here: one or several", previews: "Its preview is the picture the slicer saved inside it.",
  },
};

// A project's own STL also has how many prints it needs and has; its own 3MF, the printer it's for and, per version,
// its G-code (Upload G-code for the newest; Download and Send to the printer).
// `onMove`: a Move… button, for an STL's sub-component
export function FileCard({ project, kind, file, onNewVersion, onMove }) {
  const { putProject, printers } = useData();
  const printer = file.printerId != null ? printers.find((p) => p.id === file.printerId) : null;
  const [showOlder, setShowOlder] = useState(false); // older versions start folded away
  const [deleting, setDeleting] = useState(null); // null | "file" | a version
  const [gcodeFor, setGcodeFor] = useState(null); // a 3MF version a G-code is being uploaded for
  const [latest, ...older] = file.versions;
  const bodyId = `${kind.key}-versions-${file.id}`;
  // a document's name opens it in a new tab
  const name = kind.opens ? (
    <a
      data-testid={`${kind.key}-name`}
      href={latest.view}
      target="_blank"
      rel="noopener noreferrer"
      title={`Open ${file.name} in a new tab`}
      style={nameStyle({ textDecoration: "underline", textDecorationColor: c.borderStrong, textUnderlineOffset: 3 })}
    >
      {file.name}
    </a>
  ) : (
    file.name
  );
  return (
    <Card
      testId={`${kind.key}-file`}
      dataAttrs={{ "data-file-id": file.id }}
      heading={
        <>
          <CardTitle
            lead={
              kind.key === "stl" && (
                <HaveNeed have={file.have} need={file.need} label="prints" onSave={(counts) => setProjectStlCounts(project.id, "stl", file.id, counts)} />
              )
            }
            Icon={kind.Icon}
            name={name}
            testId={`${kind.key}-name`}
            tags={(kind.key === "stl" || kind.key === "threemf") && <ProjectOnlyTag />}
          />
          {kind.key === "threemf" && (
            <span data-testid="threemf-printer" style={uiText(12, printer ? c.textMuted : c.textFaint, { whiteSpace: "nowrap" })}>
              {printer ? printer.name : "no printer"}
            </span>
          )}
          <span style={uiText(12, c.textFaint, { whiteSpace: "nowrap", marginLeft: kind.key === "threemf" ? 0 : "auto" })}>{plural(file.versions.length, "version")}</span>
          <OlderToggle count={older.length} open={showOlder} onToggle={() => setShowOlder(!showOlder)} testId={`${kind.key}-versions-toggle`} controlsId={bodyId} />
          {kind.key === "threemf" && (
            <HeadingButton
              testId="threemf-gcode-upload"
              Icon={FileCode}
              label={latest.gcodeName ? "Replace G-code" : "Upload G-code"}
              title={latest.gcodeName ? "Upload a newer G-code for its newest version" : "Upload the G-code sliced from its newest version"}
              onClick={() => setGcodeFor(latest)}
            />
          )}
          {onMove && <MoveButton testId={`${kind.key}-move`} onClick={onMove} />}
          <HeadingButton testId={`${kind.key}-new-version`} Icon={Upload} label="New version" onClick={onNewVersion} />
          <TrashButton onClick={() => setDeleting("file")} title={`Delete this ${kind.noun}, every version`} />
        </>
      }
    >
      <FileVersionRow ver={latest} isLatest opens={kind.opens} onDelete={() => setDeleting(latest)} />
      {latest.gcodeName && <GcodeLine project={project} file={file} ver={latest} printer={printer} />}
      <div id={bodyId}>
        {showOlder &&
          older.map((v) => (
            <div key={v.v}>
              <FileVersionRow ver={v} opens={kind.opens} onDelete={() => setDeleting(v)} />
              {v.gcodeName && <GcodeLine project={project} file={file} ver={v} printer={printer} />}
            </div>
          ))}
      </div>
      {gcodeFor && <GcodeUpload project={project} file={file} ver={gcodeFor} onClose={() => setGcodeFor(null)} />}
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
    </Card>
  );
}

// A project 3MF version's G-code, on a line under it: its name, Download, and Send to the 3MF's printer (asked first:
// it starts printing straight away)
function GcodeLine({ project, file, ver, printer }) {
  const [confirming, setConfirming] = useState(false);
  const [sent, setSent] = useState(null);
  return (
    <div data-testid="threemf-gcode" data-version={ver.v} style={{ display: "flex", alignItems: "center", gap: 10, padding: "0 16px 9px 108px", flexWrap: "wrap" }}>
      <FileCode size={13} color={c.textFaint} />
      <span style={uiText(12, c.textFaint)}>G-code</span>
      <span style={monoText(12, c.textPrimary, { minWidth: 0, overflowWrap: "anywhere" })}>{ver.gcodeName}</span>
      {sent && <span style={uiText(12, c.green)}>Sent to {sent.printer} and started</span>}
      <div style={{ display: "flex", gap: 6, marginLeft: "auto" }}>
        <DownloadButton href={ver.gcodeDownload} />
        {printer && (
          <button data-testid="threemf-gcode-send" onClick={() => setConfirming(true)} title={`Send this G-code to ${printer.name} and start printing it`} style={headerButton()}>
            <Send size={12} />
            Send to {printer.name}
          </button>
        )}
      </div>
      {confirming && (
        <ConfirmDialog
          title="Send to printer"
          confirmLabel="Send and print"
          tone="amber"
          onClose={() => setConfirming(false)}
          onConfirm={async () => setSent(await sendProjectGcode(project.id, file.id, ver.v))}
        >
          Send <b style={{ color: c.heading }}>{ver.gcodeName}</b> to <b style={{ color: c.heading }}>{printer.name}</b> and
          start printing it now? Make sure the bed is clear and the right filament is loaded. A file of the same name on
          the printer is replaced.
        </ConfirmDialog>
      )}
    </div>
  );
}

// Upload the G-code sliced from a project 3MF version (replacing one it had)
function GcodeUpload({ project, file, ver, onClose }) {
  const { putProject } = useData();
  const [gcode, setGcode] = useState(null);
  const { busy, error, setError, run } = useAction();
  const submit = () => {
    if (!gcode) return setError("Drop the .gcode or .bgcode file first.");
    run(async () => {
      putProject(await uploadProjectGcode({ projectId: project.id, fileId: file.id, v: ver.v, gcode }));
      onClose();
    });
  };
  return (
    <Modal title={`G-code for ${ver.filename}`} onClose={onClose}>
      <Dropzone label="Drop the .gcode or .bgcode file here" file={gcode} onFile={setGcode} accept=".gcode,.bgcode" />
      <div style={uiText(12, c.textFaint, { lineHeight: 1.6, marginBottom: 14 })}>
        It goes with <b style={{ color: c.heading }}>v{ver.v}</b>, kept next to its 3MF in the project files folder.
        {ver.gcodeName && <> It replaces <span style={monoText(12, c.textMuted)}>{ver.gcodeName}</span>.</>}
      </div>
      <ModalActions onClose={onClose} onSubmit={submit} actionLabel="Upload" submitting={busy} errorMsg={error} />
    </Modal>
  );
}

// One version: its preview (drawn like an STL's where the file allows), number, date, size, what changed, and
// Download and delete. opens: its file name opens it in a new tab (a document's)
function FileVersionRow({ ver, isLatest = false, onDelete, opens = false }) {
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
        {opens ? (
          <a
            href={ver.view}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="file-version-open"
            title={`Open ${ver.filename} in a new tab`}
            style={monoText(12, c.textPrimary, { overflowWrap: "anywhere", textDecoration: "underline", textDecorationColor: c.borderStrong, textUnderlineOffset: 3 })}
          >
            {ver.filename}
          </a>
        ) : (
          <div style={monoText(12, c.textPrimary, { overflowWrap: "anywhere" })}>{ver.filename}</div>
        )}
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
// `multiple` (the kind's own by default): several new files can be picked at once, each uploaded in turn with the same answers and note (not for a
// new version, which is one file); `folders`: a whole folder too, and `fieldsFor(file)` adds what's sent for each file
// (its sub-component, from the folder it was in)
export function UploadDialog({
  project, kind, file: existing, onClose, extra, check, fields, fieldsFor, onUploaded, onPicked, title, multiple = kind.multiple, folders = false,
}) {
  const { putProject } = useData();
  const many = multiple && !existing;
  const [picked, setPickedState] = useState(null); // a file, or with `many` a list of them
  const setPicked = (f) => {
    setPickedState(f);
    onPicked?.(f);
  };
  const [note, setNote] = useState("");
  const [sending, setSending] = useState(0); // with `many`: which of them is on its way (1, 2...)
  const { busy, error, setError, run } = useAction();
  const files = many ? picked || [] : picked ? [picked] : [];
  const submit = () => {
    if (!files.length) return setError(`Choose the ${kind.noun}${many ? "s" : ""} to upload.`);
    const reason = check?.();
    if (reason) return setError(reason);
    run(async () => {
      if (existing) {
        putProject(await uploadProjectFileVersion({ kind: kind.key, projectId: project.id, fileId: existing.id, file: picked, note }));
      } else {
        for (const [i, f] of files.entries()) {
          setSending(i + 1);
          try {
            putProject(await uploadProjectFile({ kind: kind.key, projectId: project.id, file: f, note, ...fields, ...fieldsFor?.(f) }));
          } catch (e) {
            if (!i) throw e;
            // the ones before it are in: keep only the rest picked, so Upload carries on from this one
            setPickedState(files.slice(i));
            await onUploaded?.();
            throw new Error(`${plural(i, kind.noun)} uploaded, then ${f.name} couldn't be: ${errorText(e)} Upload tries the rest again.`);
          }
        }
      }
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
        multiple={many}
        folders={many && folders}
      />
      {extra}
      <TextField
        label={kind.noteLabel || "What changed (optional)"}
        value={note}
        onChange={setNote}
        placeholder={kind.key === "doc" ? "e.g. Signed copy from the customer" : existing ? "e.g. Wider base" : "e.g. First design"}
      />
      {(existing || !extra) && (
        <div style={uiText(12, c.textFaint, { marginBottom: 12, lineHeight: 1.5 })}>
          It's kept as version {next} ("name ver {next}") in the project files folder chosen on the Settings page. {kind.previews}
        </div>
      )}
      <ModalActions
        onClose={onClose}
        onSubmit={submit}
        actionLabel={files.length > 1 ? `Upload ${files.length}` : "Upload"}
        submitting={busy}
        submittingLabel={files.length > 1 ? `Uploading ${sending} of ${files.length}…` : "Uploading…"}
        errorMsg={error}
      />
    </Modal>
  );
}
