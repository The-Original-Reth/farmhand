import { useState } from "react";
import { Download, Pencil, Plus, ShoppingCart, Upload } from "lucide-react";
import { addProjectPart, deleteProjectPart, updateProjectPart, uploadBom } from "../api.js";
import { c, fs, ui } from "../theme.js";
import { useData } from "../data.jsx";
import { useAction } from "../hooks/useAction.js";
import { ConfirmDialog, Modal, ModalActions } from "../components/common/dialogs.jsx";
import { Dropzone, TextField } from "../components/common/fields.jsx";
import { TrashButton } from "../components/common/ui.jsx";
import { panelBox, toolButton, uiText } from "../styles.js";
import { HaveNeed, HaveNeedLabel, plural } from "./ProjectFiles.jsx";

// The template a BOM is filled in from: the columns Upload BOM reads, in this order (only Part is needed)
const TEMPLATE = "Part,Need,Have,Link,Notes\r\n";

// Download the BOM template as "BOM Template.csv" (made here: nothing to fetch)
function downloadTemplate() {
  const url = URL.createObjectURL(new Blob([TEMPLATE], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "BOM Template.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// The BOM section's buttons, beside its heading: BOM Template (a CSV to fill in), Upload BOM, and Add part
export function BomActions({ project, onUpload, onAdd }) {
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
      <button
        data-testid="bom-template"
        onClick={downloadTemplate}
        title="Download a CSV to fill in (Part, Need, Have, Link, Notes), then Upload BOM"
        style={toolButton(12)}
      >
        <Download size={12} />
        BOM Template
      </button>
      <button data-testid="bom-upload" onClick={onUpload} style={toolButton(12)}>
        <Upload size={12} />
        Upload BOM
      </button>
      <button data-testid="part-add" onClick={onAdd} style={toolButton(12)}>
        <Plus size={12} />
        Add part
      </button>
    </div>
  );
}

// A project's BOM (bill of materials): what it needs that isn't printed, each part with how many it has and needs, a
// link to buy it, and notes. Parts are added one at a time, or many from a BOM CSV.
export function BomList({ project, adding, uploading, onClose }) {
  const [editing, setEditing] = useState(null);
  return (
    <>
      {project.parts.length === 0 ? (
        <div style={panelBox({ padding: "7px 12px", ...uiText(13, c.textFaint, { lineHeight: 1.5 }) })}>
          No parts yet. <b style={{ color: c.textMuted }}>BOM Template</b> downloads a CSV to fill in for{" "}
          <b style={{ color: c.textMuted }}>Upload BOM</b>, or <b style={{ color: c.textMuted }}>Add part</b> adds one.
        </div>
      ) : (
        <>
          {/* what the two numbers at the start of each part are, lined up over them */}
          <div style={{ marginBottom: 4 }}>
            <HaveNeedLabel needFixed testId="bom-have-need-label" />
          </div>
          <div style={panelBox({ overflow: "hidden" })}>
            {project.parts.map((part) => (
              <PartRow key={part.id} project={project} part={part} onEdit={() => setEditing(part)} />
            ))}
          </div>
        </>
      )}
      {(adding || editing) && <PartForm project={project} part={editing} onClose={() => (editing ? setEditing(null) : onClose())} />}
      {uploading && <BomUpload project={project} onClose={onClose} />}
    </>
  );
}

// One part: how many it has (changed right there) and needs (changed with Edit), its name and notes, Buy (its link,
// in a new tab), and edit and remove
function PartRow({ project, part, onEdit }) {
  const { putProject } = useData();
  const [asking, setAsking] = useState(false);
  return (
    <div
      data-testid="bom-part"
      data-part-id={part.id}
      style={{ display: "flex", alignItems: "center", gap: 10, rowGap: 4, padding: "6px 8px 6px 12px", borderBottom: `1px solid ${c.border}`, flexWrap: "wrap" }}
    >
      <HaveNeed have={part.have} need={part.need} needFixed onSave={(counts) => updateProjectPart(project.id, part.id, counts)} />
      <div style={{ flex: "1 1 240px", minWidth: 0 }}>
        <div data-testid="bom-part-name" style={uiText(13, c.heading, { overflowWrap: "anywhere" })}>{part.name}</div>
        {part.note && <div style={uiText(12, c.textFaint, { marginTop: 2, overflowWrap: "anywhere" })}>{part.note}</div>}
      </div>
      {part.link && (
        <a
          href={part.link}
          target="_blank"
          rel="noopener noreferrer"
          data-testid="bom-part-buy"
          title={`Buy: opens ${part.link}`}
          style={{ ...toolButton(12), textDecoration: "none", whiteSpace: "nowrap" }}
        >
          <ShoppingCart size={12} />
          Buy
        </a>
      )}
      <button data-testid="bom-part-edit" onClick={onEdit} title="Change it: its name, how many are needed, link and notes" aria-label={`Edit ${part.name}`} style={toolButton(12)}>
        <Pencil size={12} />
      </button>
      <TrashButton onClick={() => setAsking(true)} title="Remove it from the BOM" />
      {asking && (
        <ConfirmDialog
          title="Remove part"
          confirmLabel="Yes, remove it"
          tone="warn"
          onClose={() => setAsking(false)}
          onConfirm={async () => putProject(await deleteProjectPart(project.id, part.id))}
        >
          Are you sure you want to remove <strong>{part.name}</strong> from the BOM of {project.name}?
        </ConfirmDialog>
      )}
    </div>
  );
}

// Adding a part (no `part`), or changing one: its name, how many are needed and had, a link to buy it and notes
function PartForm({ project, part, onClose }) {
  const { putProject } = useData();
  const [name, setName] = useState(part?.name || "");
  const [need, setNeed] = useState(String(part?.need ?? 1));
  const [have, setHave] = useState(String(part?.have ?? 0));
  const [link, setLink] = useState(part?.link || "");
  const [note, setNote] = useState(part?.note || "");
  const { busy, error, setError, run } = useAction();
  const submit = () => {
    const n = Number(need);
    const h = Number(have);
    if (!name.trim()) return setError("Give the part a name.");
    if (!Number.isInteger(n) || n < 1) return setError("How many are needed must be a whole number, 1 or more.");
    if (!Number.isInteger(h) || h < 0) return setError("How many you have must be a whole number, 0 or more.");
    run(async () => {
      const fields = { name: name.trim(), need: n, have: h, link: link.trim() || null, note: note.trim() || null };
      putProject(await (part ? updateProjectPart(project.id, part.id, fields) : addProjectPart(project.id, fields)));
      onClose();
    });
  };
  return (
    <Modal title={part ? `Edit ${part.name}` : "Add a part"} onClose={onClose}>
      <div onKeyDown={(e) => e.key === "Enter" && e.target.tagName === "INPUT" && submit()}>
        <TextField label="Part" value={name} onChange={setName} placeholder="e.g. M3x12 screw" />
        <div style={{ display: "flex", gap: 12 }}>
          <div style={{ flex: 1 }}>
            <TextField label="Have" type="number" value={have} onChange={setHave} />
          </div>
          <div style={{ flex: 1 }}>
            <TextField label="Need" type="number" value={need} onChange={setNeed} />
          </div>
        </div>
        <TextField label="Link to buy it (optional)" value={link} onChange={setLink} placeholder="e.g. https://www.amazon.com/..." />
        <TextField label="Notes (optional)" value={note} onChange={setNote} placeholder="e.g. black, pack of 100, which drawer" />
      </div>
      <ModalActions onClose={onClose} onSubmit={submit} actionLabel={part ? "Save" : "Add part"} submitting={busy} submittingLabel="Saving…" errorMsg={error} />
    </Modal>
  );
}

// Upload a BOM: a CSV (the Template, filled in), its parts added to the BOM or replacing it. A file with mistakes
// changes nothing, and says which rows.
function BomUpload({ project, onClose }) {
  const { putProject } = useData();
  const [file, setFile] = useState(null);
  const [replace, setReplace] = useState(false);
  const { busy, error, setError, run } = useAction();
  const submit = () => {
    if (!file) return setError("Choose the BOM's CSV file.");
    run(async () => {
      const r = await uploadBom({ projectId: project.id, file, replace });
      putProject(r.project);
      onClose();
    });
  };
  const option = (value, label) => (
    <label style={{ display: "flex", alignItems: "center", gap: 8, ...ui, fontSize: fs(13), color: c.textPrimary, marginBottom: 6, cursor: "pointer" }}>
      <input type="radio" name="bom-replace" data-testid={`bom-${value ? "replace" : "add"}`} checked={replace === value} onChange={() => setReplace(value)} style={{ accentColor: c.amber }} />
      {label}
    </label>
  );
  return (
    <Modal title="Upload BOM" onClose={onClose}>
      <Dropzone label="Drop the BOM's CSV file here" file={file} onFile={setFile} accept=".csv" />
      <div style={uiText(12, c.textFaint, { lineHeight: 1.6, marginBottom: 12 })}>
        A CSV whose first row names its columns: Part, Need, Have, Link, Notes, as in the <b style={{ color: c.textMuted }}>BOM Template</b>{" "}
        (only Part is needed; a blank Need is 1 and a blank Have is 0). Saved from Excel or Google Sheets as CSV is fine.
      </div>
      {project.parts.length > 0 && (
        <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, padding: 12, marginBottom: 12, background: c.panelAlt }}>
          {option(false, `Add its parts to the ${plural(project.parts.length, "part")} already here`)}
          {option(true, "Replace the BOM with it")}
        </div>
      )}
      <ModalActions onClose={onClose} onSubmit={submit} actionLabel="Upload" submitting={busy} errorMsg={error} />
    </Modal>
  );
}
