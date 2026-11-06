import { useState } from "react";
import { Box, ChevronDown, Download, ExternalLink, Folder, FolderInput, Layers, Plus, Upload, X } from "lucide-react";
import { addProjectModel, API_BASE, deleteProjectFile, removeProjectModel, setProjectStlCounts } from "../api.js";
import { c, fs, ui } from "../theme.js";
import { useData } from "../data.jsx";
import { useAction } from "../hooks/useAction.js";
import { AddModelFileForm } from "../models/modelActions.jsx";
import { nameCollator } from "../models/modelSort.js";
import { ConfirmDialog, DeleteWarning, Modal, ModalActions } from "../components/common/dialogs.jsx";
import { folderPathOf, TextField } from "../components/common/fields.jsx";
import { DownloadButton, TrashButton } from "../components/common/ui.jsx";
import { toolButton, uiText } from "../styles.js";
import { FILE_KINDS, FileCard, HaveNeed, UploadDialog } from "./ProjectFiles.jsx";
import {
  Card, CardTitle, EmptyBox, HeadingButton, InModelsTag, MoveButton, nameStyle, OlderToggle, PickDialog, plural, ProjectOnlyTag, TakeOutButton,
  VersionLine,
} from "./pieces.jsx";

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

// A sub-component as it's shown: "Body/Fins" is "Body / Fins"
const shown = (component) => component.split("/").join(" / ");

// The STLs in the project's sub-components: those in none first, then each sub-component, by name ("Body" just before
// "Body/Fins"). [{ component (null: none), items }]
function inComponents(items) {
  const named = new Map();
  for (const item of items.filter((i) => i.component)) {
    if (!named.has(item.component)) named.set(item.component, []);
    named.get(item.component).push(item);
  }
  return [
    { component: null, items: items.filter((i) => !i.component) },
    ...[...named.keys()].sort(nameCollator.compare).map((component) => ({ component, items: named.get(component) })),
  ];
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

// The STLs side by side, as many to a row as fit
function TileGrid({ children }) {
  return <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 10 }}>{children}</div>;
}

// A small button on a tile: just an icon (what it does on hover), or a link when `href` is given
function TileButton({ testId, Icon, title, onClick, href, children }) {
  const style = toolButton(12, { padding: "4px 7px", gap: 4, textDecoration: "none", whiteSpace: "nowrap" });
  return href ? (
    <a data-testid={testId} href={href} title={title} aria-label={title} style={style}>
      <Icon size={13} />
    </a>
  ) : (
    <button data-testid={testId} onClick={onClick} title={title} aria-label={title} style={style}>
      <Icon size={13} />
      {children}
    </button>
  );
}

// One STL as a tile: its newest version's preview (click it for every version), its name and tag, its newest version
// and date, how many prints it has and needs, and Download, Move, Versions and `last` (a trash can, or Take out)
function StlTile({ testId, dataAttrs, name, thumb, tag, ver, versions, haveNeed, download, onMove, onDetails, last }) {
  return (
    <div data-testid={testId} {...dataAttrs} style={{ border: `1px solid ${c.border}`, borderRadius: 4, overflow: "hidden", display: "flex", flexDirection: "column", minWidth: 0 }}>
      <button
        data-testid="stl-tile-preview"
        onClick={onDetails}
        title={`${name}: show every version`}
        style={{ display: "flex", alignItems: "center", justifyContent: "center", width: "100%", aspectRatio: "4 / 3", padding: 0, border: "none", borderBottom: `1px solid ${c.border}`, background: "#FFFFFF", cursor: "pointer" }}
      >
        {thumb ? (
          <img src={thumb} alt="" loading="lazy" decoding="async" style={{ width: "100%", height: "100%", objectFit: "contain", display: "block" }} />
        ) : (
          <Box size={36} color="#C7CACC" />
        )}
      </button>
      <div style={{ padding: "7px 8px 8px", display: "flex", flexDirection: "column", gap: 6, background: c.panelAlt, flex: 1 }}>
        <div data-testid="stl-name" title={name} style={nameStyle({ minWidth: 0 })}>
          {name}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          {tag}
          {ver && <span style={uiText(11, c.textFaint, { whiteSpace: "nowrap" })}>v{ver.v}{ver.date ? ` · ${ver.date}` : ""}</span>}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }} title="Prints: have / need">
          <span style={uiText(11, c.textFaint)}>Prints</span>
          {haveNeed}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 5, marginTop: "auto" }}>
          {download && <TileButton testId="stl-tile-download" Icon={Download} title="Download its newest version" href={download} />}
          <TileButton testId="stl-tile-move" Icon={FolderInput} title="Move it to another sub-component" onClick={onMove} />
          <TileButton testId="stl-tile-versions" Icon={Layers} title="Every version, New version and the rest" onClick={onDetails}>
            {versions}
          </TileButton>
          <span style={{ marginLeft: "auto" }}>{last}</span>
        </div>
      </div>
    </div>
  );
}

// An uploaded STL's trash can: deletes it, every version (asked first)
function DeleteStl({ project, file }) {
  const { putProject } = useData();
  const [asking, setAsking] = useState(false);
  return (
    <>
      <TrashButton onClick={() => setAsking(true)} title="Delete this STL file, every version" />
      {asking && (
        <ConfirmDialog
          title="Delete STL file"
          confirmLabel="Delete"
          onClose={() => setAsking(false)}
          onConfirm={async () => putProject(await deleteProjectFile("stl", project.id, file.id))}
        >
          Delete <strong>{file.name}</strong> and {file.versions.length === 1 ? "its only version" : `all ${file.versions.length} versions`}?
          <DeleteWarning>The files are deleted for good.</DeleteWarning>
        </ConfirmDialog>
      )}
    </>
  );
}

// One sub-component: its name and how many STLs are in it (click to fold them away), then its STLs, set in a little
function ComponentGroup({ component, count, open, onToggle, children }) {
  const bodyId = `stl-component-${component}`;
  return (
    <div data-testid="stl-component" data-component={component} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <button
        data-testid="stl-component-toggle"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={onToggle}
        title={open ? "Fold it away" : "Show its STLs"}
        style={{ display: "flex", alignItems: "center", gap: 8, background: "none", border: "none", padding: "4px 0 0", cursor: "pointer", textAlign: "left", ...ui }}
      >
        <ChevronDown size={14} color={c.textFaint} style={{ transform: open ? "none" : "rotate(-90deg)", transition: "transform 0.12s ease", flexShrink: 0 }} />
        <Folder size={14} color={c.amber} style={{ flexShrink: 0 }} />
        <span style={uiText(14, c.heading, { wordBreak: "break-word" })}>{shown(component)}</span>
        <span style={uiText(12, c.textFaint, { whiteSpace: "nowrap" })}>{plural(count, "STL")}</span>
      </button>
      {open && (
        <div id={bodyId} style={{ display: "flex", flexDirection: "column", gap: 10, paddingLeft: 14, borderLeft: `2px solid ${c.border}`, marginLeft: 6 }}>
          {children}
        </div>
      )}
    </div>
  );
}

// Moving an STL to another sub-component: one of the project's, picked, or a new one typed ("Body / Fins" for one
// inside another); left blank, it's in none
function MoveDialog({ project, item, components, onClose }) {
  const { putProject } = useData();
  const [name, setName] = useState(item.component ? shown(item.component) : "");
  const { busy, error, run } = useAction();
  const move = () =>
    run(async () => {
      putProject(await setProjectStlCounts(project.id, item.kind, item.id, { component: name.trim() || null }));
      onClose();
    });
  return (
    <Modal title={`Move ${item.name}`} onClose={onClose}>
      {components.length > 0 && (
        <div style={{ marginBottom: 14 }}>
          <div style={uiText(12, c.textFaint, { marginBottom: 6 })}>The project's sub-components</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {components.map((comp) => (
              <button
                key={comp}
                data-testid="stl-move-pick"
                onClick={() => setName(shown(comp))}
                style={toolButton(12, shown(comp) === name.trim() ? { borderColor: c.amber, color: c.heading } : {})}
              >
                <Folder size={12} />
                {shown(comp)}
              </button>
            ))}
          </div>
        </div>
      )}
      <TextField label="Sub-component (a / puts one inside another: Body / Fins)" value={name} onChange={setName} placeholder="e.g. Fins" />
      <div style={uiText(12, c.textFaint, { marginBottom: 12, lineHeight: 1.5 })}>
        Type a new name to start a sub-component, or leave it blank to take {item.name} out of any.
      </div>
      <ModalActions onClose={onClose} onSubmit={move} actionLabel="Move" submitting={busy} submittingLabel="Moving…" errorMsg={error} />
    </Modal>
  );
}

// A model from the Models page in the project: have / need, its name, "In Models", its newest version with its preview
// (the older ones behind the down arrow), and New version, Open in Models and Take out of project. It IS the model in
// Models, not a copy: a new version uploaded here is that model's new version, on the Models page too.
function ModelCard({ project, model, onOpen, onMove }) {
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

// The sub-component each file picked with its folders goes in: the folders it was in, below the one chosen. Files from
// one folder ("Shark/Fins/Fin.stl") go by the folders inside it ("Fins"), and those straight in it in none; files or
// folders dropped side by side ("Fins/Fin.stl", "Tail.stl") by their own folders. Map file -> "Fins" | "Body/Fins" | null
function componentsFromFolders(files) {
  const folders = files.map((f) => folderPathOf(f).split("/").filter(Boolean).slice(0, -1));
  const top = folders[0]?.[0];
  const oneFolder = top != null && folders.every((parts) => parts[0] === top);
  return new Map(files.map((f, i) => [f, folders[i].slice(oneFolder ? 1 : 0).join("/") || null]));
}

// An STL uploaded on the project's page, and the question that comes with it: also put it in Models (a new model
// there, which the project uses), or keep it in this project only (it belongs to the project). Several can be picked,
// or a whole folder: each file then goes in the sub-component named by the folder it was in.
function UploadStl({ project, onClose }) {
  const { refresh } = useData();
  const [inModels, setInModels] = useState(null); // null until answered: "yes" | "no"
  const [components, setComponents] = useState(new Map()); // file -> its sub-component (componentsFromFolders)
  const counted = new Map();
  for (const comp of components.values()) counted.set(comp, (counted.get(comp) || 0) + 1);
  const named = [...counted.keys()].filter(Boolean).sort(nameCollator.compare);
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
      multiple
      folders
      onClose={onClose}
      onPicked={(files) => setComponents(componentsFromFolders(files || []))}
      check={() => (inModels ? null : "Choose whether to also put them in Models.")}
      fields={{ inModels: inModels === "yes" }}
      fieldsFor={(f) => ({ component: components.get(f) || undefined })}
      onUploaded={() => (inModels === "yes" ? refresh() : null)}
      extra={
        <>
          {named.length > 0 && (
            <div data-testid="stl-upload-components" style={uiText(12, c.textMuted, { marginTop: -6, marginBottom: 14, lineHeight: 1.6 })}>
              From the folders, into {plural(named.length, "sub-component")}:{" "}
              {named.map((comp) => `${shown(comp)} (${counted.get(comp)})`).join(", ")}
              {counted.get(null) ? `; ${counted.get(null)} not in one` : ""}.
            </div>
          )}
          <div data-testid="stl-in-models" style={{ border: `1px solid ${c.border}`, borderRadius: 4, padding: 12, marginBottom: 14, background: c.panelAlt }}>
            <div style={uiText(13, c.heading, { marginBottom: 10 })}>Also put them in Models?</div>
            {option("yes", "Yes, put them in Models too", "Each becomes a model on the Models page, kept in the STL folder, and this project uses it.")}
            {option("no", "No, keep them in this project only", "Each belongs to this project: kept in the project files folder, with versions, and deleted with the project.")}
          </div>
        </>
      }
    />
  );
}
