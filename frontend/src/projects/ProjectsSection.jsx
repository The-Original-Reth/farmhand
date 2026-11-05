import { useState } from "react";
import { Box, FileBox, FolderKanban, Pencil, PenTool, Plus, Printer, Wrench } from "lucide-react";
import { createProject, deleteProject, renameProject } from "../api.js";
import { c } from "../theme.js";
import { useData } from "../data.jsx";
import { useAction } from "../hooks/useAction.js";
import { readStoredObject, writeStored } from "../lib/storage.js";
import { nameCollator } from "../models/modelSort.js";
import { ConfirmDialog, DeleteWarning, Modal, ModalActions } from "../components/common/dialogs.jsx";
import { TextField } from "../components/common/fields.jsx";
import { Row, SectionToggle, TrashButton } from "../components/common/ui.jsx";
import { panelBox, toolButton, uiText } from "../styles.js";
import { CadFiles, UploadCadButton } from "./CadSection.jsx";

// The Projects page: the list of projects, or one project's own page
export function ProjectsSection({ path, setPath }) {
  const view = path[1]; // {projectId}
  return view ? (
    <ProjectPage projectId={view.projectId} onDeleted={() => setPath([path[0]])} />
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

// What a project is made of, in page order. Each section folds away. CAD is built; the others are empty for now.
const PROJECT_SECTIONS = [
  { key: "cad", label: "CAD", Icon: PenTool, empty: "No CAD files yet." },
  { key: "stl", label: "STL files", Icon: Box, empty: "No STL files yet." },
  { key: "threemf", label: "3MF files", Icon: FileBox, empty: "No 3MF files yet." },
  { key: "printers", label: "Printers", Icon: Printer, empty: "No printers yet." },
  { key: "parts", label: "Parts", Icon: Wrench, empty: "No parts yet." },
];

function ProjectPage({ projectId, onDeleted }) {
  const { projects, refresh } = useData();
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [uploadingCad, setUploadingCad] = useState(false);
  const sections = useProjectSections();
  const project = projects.find((p) => p.id === projectId);
  if (!project) return null;

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

      {PROJECT_SECTIONS.map(({ key, label, Icon, empty }) => {
        const open = sections.isOpen(key);
        const bodyId = `project-section-${key}`;
        return (
          <div key={key} data-testid={`project-section-${key}`}>
            <div style={{ minHeight: 26, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: open ? 6 : 0 }}>
              <SectionToggle open={open} onToggle={() => sections.toggle(key)} controlsId={bodyId} testId={`project-toggle-${key}`}>
                <Icon size={14} />
                {label}
                {key === "cad" && ` (${project.cadFiles.length})`}
              </SectionToggle>
              {open && key === "cad" && <UploadCadButton onClick={() => setUploadingCad(true)} />}
            </div>
            {open && (
              <div id={bodyId}>
                {key === "cad" ? (
                  <CadFiles project={project} uploading={uploadingCad} onCloseUpload={() => setUploadingCad(false)} />
                ) : (
                  <div style={panelBox({ padding: "7px 12px", ...uiText(13, c.textFaint) })}>{empty}</div>
                )}
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
          {project.cadFiles.length > 0 && (
            <DeleteWarning>
              Its {project.cadFiles.length === 1 ? "CAD file" : `${project.cadFiles.length} CAD files`}, with every version, {project.cadFiles.length === 1 ? "is" : "are"} deleted for good.
            </DeleteWarning>
          )}
        </ConfirmDialog>
      )}
    </div>
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
