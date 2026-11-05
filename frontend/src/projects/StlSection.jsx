import { useState } from "react";
import { Box, ExternalLink, Plus, Upload } from "lucide-react";
import { addProjectModel, API_BASE, removeProjectModel, setProjectStlCounts } from "../api.js";
import { c, fs, ui } from "../theme.js";
import { useData } from "../data.jsx";
import { AddModelFileForm } from "../models/modelActions.jsx";
import { Modal } from "../components/common/dialogs.jsx";
import { DownloadButton } from "../components/common/ui.jsx";
import { toolButton, uiText } from "../styles.js";
import { FILE_KINDS, FileCard, HaveNeed, HaveNeedLabel, UploadDialog } from "./ProjectFiles.jsx";
import { Card, CardTitle, EmptyBox, HeadingButton, InModelsTag, OlderToggle, PickDialog, plural, TakeOutButton, VersionLine } from "./pieces.jsx";

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
  return (
    <>
      {models.length + project.stlFiles.length === 0 ? (
        <EmptyBox>
          No STL files yet. <b style={{ color: c.textMuted }}>Add from Models</b> uses a model already in Farmhand;{" "}
          <b style={{ color: c.textMuted }}>Upload STL</b> adds a new one.
        </EmptyBox>
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

// A model from the Models page in the project: have / need, its name, "In Models", its newest version with its preview
// (the older ones behind the down arrow), and New version, Open in Models and Take out of project. It IS the model in
// Models, not a copy: a new version uploaded here is that model's new version, on the Models page too.
function ModelCard({ project, model, onOpen }) {
  const { putProject } = useData();
  const [uploading, setUploading] = useState(false);
  const [showOlder, setShowOlder] = useState(false);
  const [latest, ...older] = model.versions;
  const counts = project.modelCounts[model.id];
  const line = (v, isLatest) => (
    <VersionLine key={v.v} testId="stl-model-version" ver={v} isLatest={isLatest} thumb={v.thumb} details={[v.date, v.note].filter(Boolean).join(" · ")}>
      <DownloadButton href={`${API_BASE}/source-models/${model.id}/versions/${v.v}/download`} />
    </VersionLine>
  );
  return (
    <Card
      testId="stl-model"
      dataAttrs={{ "data-model-id": model.id }}
      heading={
        <>
          <CardTitle
            lead={
              <HaveNeed
                have={counts?.have ?? 0}
                need={counts?.need ?? 1}
                label="prints"
                onSave={(change) => setProjectStlCounts(project.id, "model", model.id, change)}
              />
            }
            Icon={Box}
            name={model.name}
            tags={<InModelsTag title="This is the model on the Models page: a new version uploaded here is its new version there too" />}
          />
          <span style={uiText(12, c.textFaint, { whiteSpace: "nowrap", marginLeft: "auto" })}>{plural(model.versions.length, "version")}</span>
          <OlderToggle count={older.length} open={showOlder} onToggle={() => setShowOlder(!showOlder)} testId="stl-model-versions-toggle" />
          <HeadingButton
            testId="stl-model-new-version"
            Icon={Upload}
            label={latest ? "New version" : "Add file"}
            title="Upload a newer version: it's this model's new version on the Models page too"
            onClick={() => setUploading(true)}
          />
          <HeadingButton testId="stl-open-model" Icon={ExternalLink} label="Open in Models" title="Open it on the Models page" onClick={onOpen} />
          <TakeOutButton testId="stl-take-out" onConfirm={async () => putProject(await removeProjectModel(project.id, model.id))}>
            Take <strong>{model.name}</strong> out of {project.name}? It stays in Models: nothing is deleted.
          </TakeOutButton>
        </>
      }
    >
      {latest ? (
        <>
          {line(latest, true)}
          {showOlder && older.map((v) => line(v, false))}
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
    </Card>
  );
}

// Picking models from the Models page to use: every model not in the project yet
function AddFromModels({ project, onClose }) {
  const { sourceModels } = useData();
  const items = sourceModels
    .filter((m) => !project.modelIds.includes(m.id))
    .map((m) => ({ id: m.id, name: m.name, sub: `${m.type} · ${plural(m.versions.length, "version")}`, thumb: m.thumb }));
  return (
    <PickDialog
      title={`Add models to ${project.name}`}
      noun="models"
      searchPlaceholder="Search models…"
      items={items}
      allTaken="Every model in Models is in this project already."
      add={(id) => addProjectModel(project.id, id)}
      pickTestId="stl-pick"
      onClose={onClose}
    />
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
