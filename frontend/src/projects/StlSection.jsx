import { useState } from "react";
import { Box, ChevronDown, ExternalLink, Plus, Upload } from "lucide-react";
import { addProjectModel, API_BASE, removeProjectModel, setProjectStlCounts } from "../api.js";
import { c, fs, ui } from "../theme.js";
import { useData } from "../data.jsx";
import { useAction } from "../hooks/useAction.js";
import { nameCollator } from "../models/modelSort.js";
import { AddModelFileForm } from "../models/modelActions.jsx";
import { ConfirmDialog, Modal } from "../components/common/dialogs.jsx";
import { SearchBox } from "../components/common/fields.jsx";
import { DownloadButton, Row, Thumb } from "../components/common/ui.jsx";
import { monoText, panelBox, primaryButton, toolButton, uiText } from "../styles.js";
import { FILE_KINDS, FileCard, HaveNeed, HaveNeedLabel, plural, UploadDialog } from "./ProjectFiles.jsx";

const STL = FILE_KINDS.stl;

// The STL section's buttons: Add from Models, and Upload STL
export function StlActions({ onAdd, onUpload }) {
  return (
    <div style={{ display: "flex", gap: 8 }}>
      <button data-testid="stl-add-from-models" onClick={onAdd} style={toolButton(12)}>
        <Plus size={12} />
        Add from Models
      </button>
      <button data-testid="stl-upload" onClick={onUpload} style={toolButton(12)}>
        <Upload size={12} />
        Upload STL
      </button>
    </div>
  );
}

// A project's STL files, two kinds: models from the Models page it uses (each opens there, and taking one out of the
// project leaves it in Models), and STLs uploaded to the project only, which belong to it (versioned like its CAD files).
export function StlFiles({ project, adding, uploading, onCloseAdd, onCloseUpload, onOpenModel }) {
  const { sourceModels } = useData();
  const [newVersionOf, setNewVersionOf] = useState(null);
  const models = project.modelIds.map((id) => sourceModels.find((m) => m.id === id)).filter(Boolean);
  const count = models.length + project.stlFiles.length;
  return (
    <>
      {count === 0 ? (
        <div style={panelBox({ padding: "7px 12px", ...uiText(13, c.textFaint, { lineHeight: 1.5 }) })}>
          No STL files yet. <b style={{ color: c.textMuted }}>Add from Models</b> uses a model already in Farmhand;{" "}
          <b style={{ color: c.textMuted }}>Upload STL</b> adds a new one.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {/* what the two numbers at the start of each card are, lined up over them */}
          <div style={{ marginBottom: -6 }}>
            <HaveNeedLabel testId="stl-have-need-label" />
          </div>
          {models.map((m) => (
            <ModelCard key={`m${m.id}`} project={project} model={m} onOpen={() => onOpenModel(m.id)} />
          ))}
          {project.stlFiles.map((f) => (
            <FileCard key={`f${f.id}`} project={project} kind={STL} file={f} onNewVersion={() => setNewVersionOf(f)} />
          ))}
        </div>
      )}
      {adding && <AddFromModels project={project} onClose={onCloseAdd} />}
      {uploading && <UploadStl project={project} onClose={onCloseUpload} />}
      {newVersionOf && <UploadDialog project={project} kind={STL} file={newVersionOf} onClose={() => setNewVersionOf(null)} />}
    </>
  );
}

// A model from the Models page in the project: its name, "In Models", its newest version with its preview (the older
// ones behind the down arrow), and New version, Open in Models and Take out of project. It IS the model in Models, not a
// copy: a new version uploaded here is that model's new version, on the Models page too.
function ModelCard({ project, model, onOpen }) {
  const { putProject } = useData();
  const [asking, setAsking] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [showOlder, setShowOlder] = useState(false); // older versions start folded away
  const [latest, ...older] = model.versions;
  const row = (v, isLatest) => (
    <div key={v.v} data-testid="stl-model-version" data-version={v.v} style={{ display: "flex", alignItems: "center", gap: 14, padding: "10px 16px", borderTop: `1px solid ${c.border}`, flexWrap: "wrap" }}>
      <Thumb src={v.thumb} size={64} background="#FFFFFF" placeholderIcon />
      <span style={monoText(12, isLatest ? c.amber : c.textFaint, { width: 30 })}>v{v.v}</span>
      <div style={{ flex: "1 1 220px", minWidth: 0, ...uiText(12, c.textFaint) }}>{[v.date, v.note].filter(Boolean).join(" · ")}</div>
      <div style={{ marginLeft: "auto" }}>
        <DownloadButton href={`${API_BASE}/source-models/${model.id}/versions/${v.v}/download`} />
      </div>
    </div>
  );
  return (
    <div data-testid="stl-model" data-model-id={model.id} style={{ border: `1px solid ${c.border}`, borderRadius: 4, overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, rowGap: 4, flexWrap: "wrap", padding: "5px 8px 5px 12px", background: c.panelAlt }}>
        <span style={{ display: "flex", alignItems: "center", gap: 8, flex: "1 1 220px", minWidth: 0 }}>
          {/* have / need at the start of the heading, left of the name */}
          <HaveNeed
            have={project.modelCounts[model.id]?.have ?? 0}
            need={project.modelCounts[model.id]?.need ?? 1}
            label="prints"
            onSave={(counts) => setProjectStlCounts(project.id, "model", model.id, counts)}
          />
          <Box size={14} color={c.textFaint} style={{ flexShrink: 0 }} />
          <span title={model.name} style={monoText(13, c.heading, { minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" })}>
            {model.name}
          </span>
          <span
            title="This is the model on the Models page: a new version uploaded here is its new version there too"
            style={uiText(11, c.textMuted, { border: `1px solid ${c.borderStrong}`, borderRadius: 3, padding: "0 6px", whiteSpace: "nowrap" })}
          >
            In Models
          </span>
        </span>
        <span style={uiText(12, c.textFaint, { whiteSpace: "nowrap", marginLeft: "auto" })}>{plural(model.versions.length, "version")}</span>
        {older.length > 0 && (
          <button
            data-testid="stl-model-versions-toggle"
            aria-expanded={showOlder}
            onClick={() => setShowOlder(!showOlder)}
            title={showOlder ? `Hide ${plural(older.length, "older version")}` : `Show ${plural(older.length, "older version")}`}
            style={toolButton(12, { whiteSpace: "nowrap" })}
          >
            <ChevronDown size={12} style={{ transform: showOlder ? "rotate(180deg)" : "none", transition: "transform 0.12s ease" }} />
            {older.length} older
          </button>
        )}
        <button
          data-testid="stl-model-new-version"
          onClick={() => setUploading(true)}
          title="Upload a newer version: it's this model's new version on the Models page too"
          style={toolButton(12, { whiteSpace: "nowrap" })}
        >
          <Upload size={12} />
          {latest ? "New version" : "Add file"}
        </button>
        <button data-testid="stl-open-model" onClick={onOpen} title="Open it on the Models page" style={toolButton(12, { whiteSpace: "nowrap" })}>
          <ExternalLink size={12} />
          Open in Models
        </button>
        <button data-testid="stl-take-out" onClick={() => setAsking(true)} title="Take it out of this project" style={toolButton(12, { whiteSpace: "nowrap" })}>
          Take out
        </button>
      </div>
      {latest ? (
        <>
          {row(latest, true)}
          {showOlder && older.map((v) => row(v, false))}
        </>
      ) : (
        <div style={{ padding: "8px 16px", borderTop: `1px solid ${c.border}`, ...uiText(12, c.textFaint) }}>No file in this model yet.</div>
      )}
      {uploading && (
        <Modal title={latest ? `New version of ${model.name}` : `Add a file to ${model.name}`} onClose={() => setUploading(false)}>
          <div style={uiText(12, c.textFaint, { lineHeight: 1.6, marginBottom: 10 })}>
            This is the model on the Models page, so it's updated there too (and in every project that uses it).
          </div>
          <AddModelFileForm model={model} isNewVersion={!!latest} onClose={() => setUploading(false)} />
        </Modal>
      )}
      {asking && (
        <ConfirmDialog
          title="Take out of project"
          confirmLabel="Take it out"
          tone="warn"
          onClose={() => setAsking(false)}
          onConfirm={async () => putProject(await removeProjectModel(project.id, model.id))}
        >
          Take <strong>{model.name}</strong> out of {project.name}? It stays in Models: nothing is deleted.
        </ConfirmDialog>
      )}
    </div>
  );
}

// Picking models from the Models page to use: every model not in the project yet, searchable. Each is added at once,
// and the dialog stays open for the next.
function AddFromModels({ project, onClose }) {
  const { sourceModels, putProject } = useData();
  const [query, setQuery] = useState("");
  const { busy, error, run } = useAction();
  const inProject = new Set(project.modelIds);
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const choices = sourceModels
    .filter((m) => !inProject.has(m.id))
    .filter((m) => words.every((w) => m.name.toLowerCase().includes(w)))
    .sort((a, b) => nameCollator.compare(a.name, b.name));
  return (
    <Modal title={`Add models to ${project.name}`} onClose={onClose} width={560}>
      <SearchBox value={query} onChange={setQuery} placeholder="Search models…" label="Search models" style={{ marginBottom: 12 }} />
      {error && <div style={uiText(12, c.amber, { marginBottom: 10 })}>{error}</div>}
      <div style={panelBox({ overflow: "hidden", maxHeight: "50vh", overflowY: "auto" })}>
        {choices.length === 0 ? (
          <div style={{ padding: 16, ...uiText(13, c.textFaint) }}>
            {sourceModels.length === inProject.size ? "Every model in Models is in this project already." : "No models match."}
          </div>
        ) : (
          choices.map((m) => (
            <Row key={m.id} hoverable={false}>
              <Thumb src={m.thumb} size={36} background="#FFFFFF" placeholderIcon />
              <div style={{ flex: 1, minWidth: 0, marginLeft: 12 }}>
                <div style={uiText(13, c.textPrimary, { overflowWrap: "anywhere" })}>{m.name}</div>
                <div style={uiText(12, c.textFaint, { marginTop: 2 })}>{m.type} · {plural(m.versions.length, "version")}</div>
              </div>
              <button
                disabled={busy}
                data-testid={`stl-pick-${m.id}`}
                onClick={() => run(async () => putProject(await addProjectModel(project.id, m.id)))}
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

// An STL uploaded on the project's page, and the question that comes with it: also put it in Models (a new model
// there, which the project uses), or keep it in this project only (it belongs to the project).
function UploadStl({ project, onClose }) {
  const { refresh } = useData();
  const [inModels, setInModels] = useState(null); // null until answered: "yes" | "no"
  const option = (value, title, detail) => (
    <label style={{ display: "flex", alignItems: "flex-start", gap: 8, ...ui, fontSize: fs(13), color: c.textPrimary, marginBottom: 8, cursor: "pointer" }}>
      <input
        type="radio"
        name="stl-in-models"
        data-testid={`stl-in-models-${value}`}
        checked={inModels === value}
        onChange={() => setInModels(value)}
        style={{ accentColor: c.amber, marginTop: 3 }}
      />
      <span>
        {title}
        <span style={{ display: "block", color: c.textFaint, fontSize: fs(12), marginTop: 2 }}>{detail}</span>
      </span>
    </label>
  );
  return (
    <UploadDialog
      project={project}
      kind={STL}
      onClose={onClose}
      check={() => (inModels ? null : "Choose whether to also put it in Models.")}
      fields={{ inModels: inModels === "yes" }}
      onUploaded={() => (inModels === "yes" ? refresh() : null)}
      extra={
        <div data-testid="stl-in-models" style={{ border: `1px solid ${c.border}`, borderRadius: 4, padding: 12, marginBottom: 14, background: c.panelAlt }}>
          <div style={uiText(13, c.heading, { marginBottom: 10 })}>Also put it in Models?</div>
          {option("yes", "Yes, put it in Models too", "It becomes a model on the Models page, kept in the STL folder, and this project uses it.")}
          {option("no", "No, keep it in this project only", "It belongs to this project: kept in the project files folder, with versions, and deleted with the project.")}
        </div>
      }
    />
  );
}
