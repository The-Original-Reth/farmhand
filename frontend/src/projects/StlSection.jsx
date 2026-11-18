import { useState } from "react";
import { Plus, Upload, X } from "lucide-react";
import { API_BASE, removeProjectModel, setProjectStlCounts } from "../api.js";
import { c } from "../theme.js";
import { useData } from "../data.jsx";
import { Modal } from "../components/common/dialogs.jsx";
import { toolButton } from "../styles.js";
import { FILE_KINDS, FileCard, HaveNeed, UploadDialog } from "./ProjectFiles.jsx";
import { EmptyBox, InModelsTag, ProjectOnlyTag, TakeOutButton } from "./pieces.jsx";
import { inComponents } from "./stlComponents.js";
import { ComponentGroup, DeleteStl, StlTile, TileGrid } from "./StlTiles.jsx";
import { MoveDialog } from "./StlMoveDialog.jsx";
import { ModelCard } from "./StlModelCard.jsx";
import { AddFromModels } from "./StlAddFromModels.jsx";
import { UploadStl } from "./StlUpload.jsx";

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
// Either kind can be in one of the project's sub-components (Body, Fins...), set by the folder it was uploaded from or
// with Move…, and is shown under it. They're laid out as a grid of tiles; a tile's Versions opens its whole card.
export function StlFiles({ project, adding, uploading, onCloseAdd, onCloseUpload, onOpenModel }) {
  const { sourceModels, putProject } = useData();
  const [newVersionOf, setNewVersionOf] = useState(null);
  const [moving, setMoving] = useState(null); // null | { kind: "model" | "stl", id, name, component }
  const [folded, setFolded] = useState([]); // the sub-components folded away
  const [details, setDetails] = useState(null); // the key of the item whose whole card is open
  const models = project.modelIds.map((id) => sourceModels.find((m) => m.id === id)).filter(Boolean);
  const items = [
    ...models.map((m) => {
      const component = project.modelCounts[m.id]?.component || null;
      const counts = project.modelCounts[m.id];
      const latest = m.versions[0];
      const move = () => setMoving({ kind: "model", id: m.id, name: m.name, component });
      return {
        key: `m${m.id}`,
        name: m.name,
        component,
        tile: (
          <StlTile
            key={`m${m.id}`}
            testId="stl-model"
            dataAttrs={{ "data-model-id": m.id }}
            name={m.name}
            thumb={latest?.thumb}
            tag={<InModelsTag title="This is the model on the Models page: a new version uploaded here is its new version there too" />}
            ver={latest}
            versions={m.versions.length}
            haveNeed={<HaveNeed have={counts?.have ?? 0} need={counts?.need ?? 1} label="prints" onSave={(change) => setProjectStlCounts(project.id, "model", m.id, change)} />}
            download={latest && `${API_BASE}/source-models/${m.id}/versions/${latest.v}/download`}
            onMove={move}
            onDetails={() => setDetails(`m${m.id}`)}
            last={
              <TakeOutButton
                testId="stl-take-out"
                label={<X size={12} />}
                onConfirm={async () => putProject(await removeProjectModel(project.id, m.id))}
              >
                Take <strong>{m.name}</strong> out of {project.name}? It stays in Models: nothing is deleted.
              </TakeOutButton>
            }
          />
        ),
        card: <ModelCard project={project} model={m} onOpen={() => onOpenModel(m.id)} onMove={move} />,
      };
    }),
    ...project.stlFiles.map((f) => {
      const latest = f.versions[0];
      const move = () => setMoving({ kind: "stl", id: f.id, name: f.name, component: f.component });
      return {
        key: `f${f.id}`,
        name: f.name,
        component: f.component,
        tile: (
          <StlTile
            key={`f${f.id}`}
            testId="stl-file"
            dataAttrs={{ "data-file-id": f.id }}
            name={f.name}
            thumb={latest.preview}
            tag={<ProjectOnlyTag />}
            ver={latest}
            versions={f.versions.length}
            haveNeed={<HaveNeed have={f.have} need={f.need} label="prints" onSave={(counts) => setProjectStlCounts(project.id, "stl", f.id, counts)} />}
            download={latest.download}
            onMove={move}
            onDetails={() => setDetails(`f${f.id}`)}
            last={<DeleteStl project={project} file={f} />}
          />
        ),
        card: <FileCard project={project} kind={STL} file={f} onNewVersion={() => setNewVersionOf(f)} onMove={move} />,
      };
    }),
  ];
  const open = details && items.find((i) => i.key === details); // gone once it's deleted or taken out
  const groups = inComponents(items);
  const fold = (component) => setFolded(folded.includes(component) ? folded.filter((x) => x !== component) : [...folded, component]);
  return (
    <>
      {items.length === 0 ? (
        <EmptyBox>
          No STL files yet. <b style={{ color: c.textMuted }}>Add from Models</b> uses a model already in Farmhand;{" "}
          <b style={{ color: c.textMuted }}>Upload STL</b> adds a new one, or a whole folder of them.
        </EmptyBox>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {groups.map(({ component, items: inIt }) =>
            component === null ? (
              inIt.length > 0 && <TileGrid key="none">{inIt.map((i) => i.tile)}</TileGrid>
            ) : (
              <ComponentGroup key={`c:${component}`} component={component} count={inIt.length} open={!folded.includes(component)} onToggle={() => fold(component)}>
                <TileGrid>{inIt.map((i) => i.tile)}</TileGrid>
              </ComponentGroup>
            )
          )}
        </div>
      )}
      {adding && <AddFromModels project={project} onClose={onCloseAdd} />}
      {uploading && <UploadStl project={project} onClose={onCloseUpload} />}
      {open && (
        <Modal title={open.name} width={860} onClose={() => setDetails(null)}>
          {open.card}
        </Modal>
      )}
      {newVersionOf && <UploadDialog project={project} kind={STL} file={newVersionOf} onClose={() => setNewVersionOf(null)} />}
      {moving && (
        <MoveDialog
          project={project}
          item={moving}
          components={groups.map((g) => g.component).filter(Boolean)}
          onClose={() => setMoving(null)}
        />
      )}
    </>
  );
}
