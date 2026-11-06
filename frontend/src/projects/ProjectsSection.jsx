import { useState } from "react";
import { Box, FileBox, FileText, FolderKanban, GripVertical, Pencil, PenTool, Plus, Printer, Upload, Wrench } from "lucide-react";
import { arrangeProjectFiles, createProject, deleteProject, renameProject } from "../api.js";
import { c } from "../theme.js";
import { useData } from "../data.jsx";
import { useAction } from "../hooks/useAction.js";
import { readStoredObject, writeStored } from "../lib/storage.js";
import { nameCollator } from "../models/modelSort.js";
import { ConfirmDialog, DeleteWarning, Modal, ModalActions } from "../components/common/dialogs.jsx";
import { TextField } from "../components/common/fields.jsx";
import { Row, SectionToggle, TrashButton } from "../components/common/ui.jsx";
import { panelBox, toolButton, uiText } from "../styles.js";
import { FILE_KINDS, FileCard, UploadDialog } from "./ProjectFiles.jsx";
import { EmptyBox, plural } from "./pieces.jsx";
import { StlActions, StlFiles } from "./StlSection.jsx";
import { ThreemfActions, ThreemfFiles } from "./ThreemfSection.jsx";
import { AddPrinterButton, ProjectPrinters } from "./ProjectPrinters.jsx";
import { BomActions, BomList } from "./BomSection.jsx";

// The Projects page: the list of projects, or one project's own page
// onOpenModel(modelId) / onOpenPrinter(printerId): that model's or printer's own page
export function ProjectsSection({ path, setPath, onOpenModel, onOpenPrinter }) {
  const view = path[1]; // {projectId}
  return view ? (
    <ProjectPage projectId={view.projectId} onDeleted={() => setPath([path[0]])} onOpenModel={onOpenModel} onOpenPrinter={onOpenPrinter} />
  ) : (
    <ProjectList onOpen={(id) => setPath([path[0], { projectId: id }])} />
  );
}

function ProjectList({ onOpen }) {
  const { projects } = useData();
  const [creating, setCreating] = useState(false);
  const sorted = [...projects].sort((a, b) => nameCollator.compare(a.name, b.name));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 900 }}>
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <button data-testid="project-new" onClick={() => setCreating(true)} style={toolButton(12)}>
          <Plus size={12} />
          New project
        </button>
      </div>
      {sorted.length === 0 ? (
        <div style={panelBox({ padding: 20, ...uiText(13, c.textFaint, { lineHeight: 1.6 }) })}>
          No projects yet. A project gathers what one piece of work needs: its CAD files, STL files, 3MF files, printers
          and parts. <b style={{ color: c.textMuted }}>New project</b> starts one.
        </div>
      ) : (
        <div style={panelBox({ overflow: "hidden" })}>
          {sorted.map((p) => (
            <Row key={p.id} onClick={() => onOpen(p.id)}>
              <FolderKanban size={16} color={c.textFaint} />
              <span data-testid="project-row" style={uiText(14, c.heading, { marginLeft: 12, overflowWrap: "anywhere" })}>
                {p.name}
              </span>
            </Row>
          ))}
        </div>
      )}
      {creating && (
        <Modal title="New project" onClose={() => setCreating(false)}>
          <ProjectNameForm onClose={() => setCreating(false)} onSaved={(p) => onOpen(p.id)} />
        </Modal>
      )}
    </div>
  );
}

// A new project (no `project`), or a new name for one
function ProjectNameForm({ project, onClose, onSaved }) {
  const { putProject } = useData();
  const [name, setName] = useState(project?.name || "");
  const { busy, error, setError, run } = useAction();
  const submit = () => {
    if (!name.trim()) return setError("Give the project a name.");
    run(async () => {
      const saved = putProject(await (project ? renameProject(project.id, name) : createProject(name)));
      onClose();
      onSaved?.(saved);
    });
  };
  return (
    <div onKeyDown={(e) => e.key === "Enter" && e.target.tagName === "INPUT" && submit()}>
      <TextField label="Name" value={name} onChange={setName} placeholder="e.g. Aquarium shop order" />
      <ModalActions
        onClose={onClose}
        onSubmit={submit}
        actionLabel={project ? "Rename" : "Make project"}
        submitting={busy}
        submittingLabel="Saving…"
        errorMsg={error}
      />
    </div>
  );
}

// What a project is made of, in page order. Each section folds away.
const PROJECT_SECTIONS = [
  { key: "doc", label: "Documents", Icon: FileText, count: (p) => p.docFiles.length }, // any file, with versions and notes
  { key: "cad", label: "CAD", Icon: PenTool, count: (p) => p.cadFiles.length },
  { key: "stl", label: "STL files", Icon: Box, count: (p) => p.modelIds.length + p.stlFiles.length },
  { key: "parts", label: "BOM", Icon: Wrench, count: (p) => p.parts.length }, // its parts list (bill of materials)
  { key: "threemf", label: "3MF files", Icon: FileBox, count: (p) => p.bundleIds.length + p.threemfFiles.length },
  { key: "printers", label: "Printers", Icon: Printer, count: (p) => p.printerIds.length },
];

function ProjectPage({ projectId, onDeleted, onOpenModel, onOpenPrinter }) {
  const { projects, refresh } = useData();
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  // null | "doc-upload" | "cad-upload" | "stl-add" | "stl-upload" | "threemf-add" | "threemf-upload" | "printer-add" | "part-add" | "bom-upload"
  const [dialog, setDialog] = useState(null);
  const sections = useProjectSections();
  const project = projects.find((p) => p.id === projectId);
  if (!project) return null;
  const close = () => setDialog(null);

  // each section's buttons (shown while it's open) and what's in it
  const actions = {
    doc: (
      <button data-testid="doc-upload" onClick={() => setDialog("doc-upload")} style={toolButton(12)}>
        <Upload size={12} />
        Upload document
      </button>
    ),
    cad: (
      <button data-testid="cad-upload" onClick={() => setDialog("cad-upload")} style={toolButton(12)}>
        <Upload size={12} />
        Upload CAD
      </button>
    ),
    stl: <StlActions onAdd={() => setDialog("stl-add")} onUpload={() => setDialog("stl-upload")} />,
    threemf: <ThreemfActions onAdd={() => setDialog("threemf-add")} onUpload={() => setDialog("threemf-upload")} />,
    printers: <AddPrinterButton onClick={() => setDialog("printer-add")} />,
    parts: <BomActions project={project} onUpload={() => setDialog("bom-upload")} onAdd={() => setDialog("part-add")} />,
  };
  const bodies = {
    doc: <OwnFiles project={project} kind={FILE_KINDS.doc} uploading={dialog === "doc-upload"} onCloseUpload={close} />,
    cad: <OwnFiles project={project} kind={FILE_KINDS.cad} uploading={dialog === "cad-upload"} onCloseUpload={close} />,
    stl: (
      <StlFiles
        project={project}
        adding={dialog === "stl-add"}
        uploading={dialog === "stl-upload"}
        onCloseAdd={close}
        onCloseUpload={close}
        onOpenModel={onOpenModel}
      />
    ),
    threemf: (
      <ThreemfFiles
        project={project}
        adding={dialog === "threemf-add"}
        uploading={dialog === "threemf-upload"}
        onCloseAdd={close}
        onCloseUpload={close}
        onOpenPrinter={onOpenPrinter}
      />
    ),
    printers: <ProjectPrinters project={project} adding={dialog === "printer-add"} onCloseAdd={close} onOpenPrinter={onOpenPrinter} />,
    parts: <BomList project={project} adding={dialog === "part-add"} uploading={dialog === "bom-upload"} onClose={close} />,
  };
  const ownFiles = project.docFiles.length + project.cadFiles.length + project.stlFiles.length + project.threemfFiles.length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, maxWidth: 1100 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div data-testid="project-name" style={uiText(20, c.heading, { fontWeight: 600, overflowWrap: "anywhere", minWidth: 0 })}>
          {project.name}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button data-testid="project-rename" onClick={() => setRenaming(true)} style={toolButton(12)}>
            <Pencil size={12} />
            Rename
          </button>
          <TrashButton onClick={() => setDeleting(true)} title="Delete this project" />
        </div>
      </div>

      {PROJECT_SECTIONS.map(({ key, label, Icon, count, empty }) => {
        const open = sections.isOpen(key);
        const bodyId = `project-section-${key}`;
        return (
          <div key={key} data-testid={`project-section-${key}`}>
            <div style={{ minHeight: 26, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: open ? 6 : 0 }}>
              <SectionToggle open={open} onToggle={() => sections.toggle(key)} controlsId={bodyId} testId={`project-toggle-${key}`}>
                <Icon size={14} />
                <span style={{ fontWeight: 700 }}>{label}</span>
                {count && ` (${count(project)})`}
              </SectionToggle>
              {open && actions[key]}
            </div>
            {open && (
              <div id={bodyId}>
                {bodies[key] || <div style={panelBox({ padding: "7px 12px", ...uiText(13, c.textFaint) })}>{empty}</div>}
              </div>
            )}
          </div>
        );
      })}

      {renaming && (
        <Modal title="Rename project" onClose={() => setRenaming(false)}>
          <ProjectNameForm project={project} onClose={() => setRenaming(false)} />
        </Modal>
      )}
      {deleting && (
        <ConfirmDialog
          title="Delete project"
          confirmLabel="Delete project"
          onClose={() => setDeleting(false)}
          onConfirm={async () => {
            await deleteProject(project.id);
            await refresh();
            onDeleted();
          }}
        >
          Delete the project <strong>{project.name}</strong>?
          {project.modelIds.length + project.bundleIds.length + project.printerIds.length > 0 &&
            " The models, 3MF files and printers it uses from the rest of Farmhand stay where they are."}
          {ownFiles > 0 && (
            <DeleteWarning>
              Its own {[
                project.docFiles.length > 0 && plural(project.docFiles.length, "document"),
                project.cadFiles.length > 0 && plural(project.cadFiles.length, "CAD file"),
                project.stlFiles.length > 0 && plural(project.stlFiles.length, "STL file"),
                project.threemfFiles.length > 0 && plural(project.threemfFiles.length, "3MF file"),
              ].filter(Boolean).join(", ")}, with every version, {ownFiles === 1 ? "is" : "are"} deleted for good.
            </DeleteWarning>
          )}
        </ConfirmDialog>
      )}
    </div>
  );
}

// What an empty Documents or CAD section says
const EMPTY = {
  doc: (
    <>
      No documents yet. <b style={{ color: c.textMuted }}>Upload document</b> adds any file (a quote, drawings,
      instructions, photos, a spreadsheet...) with notes; each newer version is kept, and every version can be downloaded.
    </>
  ),
  cad: (
    <>
      No CAD files yet. <b style={{ color: c.textMuted }}>Upload CAD</b> adds one of any kind (Fusion, STEP, IGES,
      SolidWorks, OpenSCAD...); each newer version is kept, and every version can be downloaded.
    </>
  ),
};

// The project's documents or CAD files (`kind`), each with its versions. They're arranged by dragging one by its grip
// (or with the arrow keys on the grip), and stay in that order.
function OwnFiles({ project, kind, uploading, onCloseUpload }) {
  const { putProject } = useData();
  const [newVersionOf, setNewVersionOf] = useState(null);
  const [grabbed, setGrabbed] = useState(null); // the id of the one held by its grip (it can then be dragged)
  const [dropAt, setDropAt] = useState(null); // while dragging: { id, after } of the one it would go before or after
  const { error, run } = useAction();
  const files = kind.list(project);
  const ids = files.map((f) => f.id);
  // move `id` to just before (or after) `target`, and save the new order
  const move = (id, target, after) => {
    const rest = ids.filter((x) => x !== id);
    const at = rest.indexOf(target) + (after ? 1 : 0);
    const next = [...rest.slice(0, at), id, ...rest.slice(at)];
    if (next.join() !== ids.join()) run(async () => putProject(await arrangeProjectFiles(kind.key, project.id, next)));
  };
  const step = (id, by) => {
    const i = ids.indexOf(id);
    const j = i + by;
    if (j >= 0 && j < ids.length) move(id, ids[j], by > 0);
  };
  const grip = (f) => (
    <button
      data-testid={`${kind.key}-grip`}
      onMouseDown={() => setGrabbed(f.id)}
      onMouseUp={() => setGrabbed(null)}
      onKeyDown={(e) => {
        if (e.key === "ArrowUp" || e.key === "ArrowDown") {
          e.preventDefault();
          step(f.id, e.key === "ArrowUp" ? -1 : 1);
        }
      }}
      title="Drag to arrange (or use the up and down arrow keys)"
      aria-label={`Move ${f.name}: up and down arrow keys`}
      style={{ display: "flex", alignItems: "center", background: "none", border: "none", padding: 0, color: c.textFaint, cursor: "grab", flexShrink: 0 }}
    >
      <GripVertical size={14} />
    </button>
  );
  const line = (where) => <div style={{ height: 2, background: c.amber, borderRadius: 1, margin: where === "before" ? "-6px 0 4px" : "4px 0 -6px" }} />;
  return (
    <>
      {error && <div style={uiText(12, c.amber, { marginBottom: 8 })}>{error}</div>}
      {files.length === 0 ? (
        <div style={panelBox({ padding: "7px 12px", ...uiText(13, c.textFaint, { lineHeight: 1.5 }) })}>{EMPTY[kind.key]}</div>
      ) : (
        <div data-testid={`${kind.key}-list`} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {files.map((f) => (
            <div
              key={f.id}
              draggable={grabbed === f.id}
              onDragStart={(e) => {
                e.dataTransfer.effectAllowed = "move";
                e.dataTransfer.setData("text/plain", String(f.id));
              }}
              onDragOver={(e) => {
                if (grabbed == null) return; // only one of these, not a file dropped from the computer
                e.preventDefault();
                const r = e.currentTarget.getBoundingClientRect();
                const after = e.clientY > r.top + r.height / 2;
                if (dropAt?.id !== f.id || dropAt.after !== after) setDropAt({ id: f.id, after });
              }}
              onDrop={(e) => {
                e.preventDefault();
                if (grabbed != null && dropAt && grabbed !== dropAt.id) move(grabbed, dropAt.id, dropAt.after);
                setGrabbed(null);
                setDropAt(null);
              }}
              onDragEnd={() => {
                setGrabbed(null);
                setDropAt(null);
              }}
              style={{ opacity: grabbed === f.id && dropAt ? 0.5 : 1 }}
            >
              {dropAt?.id === f.id && !dropAt.after && grabbed !== f.id && line("before")}
              <FileCard project={project} kind={kind} file={f} grip={grip(f)} onNewVersion={() => setNewVersionOf(f)} />
              {dropAt?.id === f.id && dropAt.after && grabbed !== f.id && line("after")}
            </div>
          ))}
        </div>
      )}
      {uploading && <UploadDialog project={project} kind={kind} onClose={onCloseUpload} />}
      {newVersionOf && <UploadDialog project={project} kind={kind} file={newVersionOf} onClose={() => setNewVersionOf(null)} />}
    </>
  );
}

// Which of a project page's sections are folded away ({ cad: true... }), the same on every project and remembered in
// this browser. Every section starts open.
const PROJECT_SECTIONS_KEY = "farmhand.projectSections";
function useProjectSections() {
  const [folded, setFolded] = useState(() => readStoredObject(PROJECT_SECTIONS_KEY));
  const toggle = (name) =>
    setFolded((prev) => {
      const next = { ...prev, [name]: !prev[name] };
      writeStored(PROJECT_SECTIONS_KEY, next);
      return next;
    });
  return { isOpen: (name) => !folded[name], toggle };
}
