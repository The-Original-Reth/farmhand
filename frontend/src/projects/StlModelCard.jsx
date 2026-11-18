// The whole card of a model from the Models page that a project uses, opened from its STL tile
import { useState } from "react";
import { Box, ExternalLink, Upload } from "lucide-react";
import { API_BASE, removeProjectModel, setProjectStlCounts } from "../api.js";
import { c } from "../theme.js";
import { useData } from "../data.jsx";
import { AddModelFileForm } from "../models/modelActions.jsx";
import { Modal } from "../components/common/dialogs.jsx";
import { DownloadButton } from "../components/common/ui.jsx";
import { uiText } from "../styles.js";
import { HaveNeed } from "./ProjectFiles.jsx";
import { Card, CardTitle, HeadingButton, InModelsTag, MoveButton, OlderToggle, TakeOutButton, VersionLine } from "./pieces.jsx";
import { plural } from "../lib/format.js";

// A model from the Models page in the project: have / need, its name, "In Models", its newest version with its preview
// (the older ones behind the down arrow), and New version, Open in Models and Take out of project. It IS the model in
// Models, not a copy: a new version uploaded here is that model's new version, on the Models page too.
export function ModelCard({ project, model, onOpen, onMove }) {
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
          <MoveButton testId="stl-model-move" onClick={onMove} />
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
