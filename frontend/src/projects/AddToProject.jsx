import { useState } from "react";
import { FolderKanban, FolderPlus } from "lucide-react";
import { addProjectBundle, addProjectModel, createProject } from "../api.js";
import { c, fs, ui } from "../theme.js";
import { useData } from "../data.jsx";
import { useAction } from "../hooks/useAction.js";
import { nameCollator } from "../lib/order.js";
import { Modal, ModalActions } from "../components/common/dialogs.jsx";
import { TextField } from "../components/common/fields.jsx";
import { toolButton, uiText } from "../styles.js";
import { plural } from "../lib/format.js";

// What can be added to a project from elsewhere: a model (from its page) or a 3MF (from its card). Its own project list,
// how it's added, and what it's called in the dialog.
const THINGS = {
  model: { ids: (p) => p.modelIds, add: addProjectModel, noun: "model" },
  bundle: { ids: (p) => p.bundleIds, add: addProjectBundle, noun: "3MF" },
};

// "Add to project" on a model's newest version (beside Download) or on a 3MF's card: it asks which project, one there
// already or a new one made there and then. Once the thing is in some, it says how many. Give `model` or `bundle`.
export function AddToProjectButton({ model, bundle }) {
  const { projects } = useData();
  const [open, setOpen] = useState(false);
  const kind = model ? "model" : "bundle";
  const thing = model || bundle;
  const inCount = projects.filter((p) => THINGS[kind].ids(p).includes(thing.id)).length;
  return (
    <>
      <button
        data-testid="add-to-project"
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
        title={inCount ? `In ${plural(inCount, "project")}: add it to another` : `Add this ${THINGS[kind].noun} to a project`}
        style={toolButton(12, { whiteSpace: "nowrap" })}
      >
        <FolderPlus size={12} />
        Add to project
        {inCount > 0 && <span style={{ color: c.textFaint }}>({inCount})</span>}
      </button>
      {open && <AddToProjectDialog kind={kind} thing={thing} onClose={() => setOpen(false)} />}
    </>
  );
}

function AddToProjectDialog({ kind, thing, onClose }) {
  const { projects, putProject } = useData();
  const [where, setWhere] = useState(null); // null until chosen: "existing" | "new"
  const [projectId, setProjectId] = useState(null);
  const [name, setName] = useState("");
  const { busy, error, setError, run } = useAction();
  const sorted = [...projects].sort((a, b) => nameCollator.compare(a.name, b.name));
  const available = sorted.filter((p) => !THINGS[kind].ids(p).includes(thing.id));

  const submit = () => {
    if (!where) return setError("Choose a project you have, or a new one.");
    if (where === "existing" && !projectId) return setError("Pick the project to add it to.");
    if (where === "new" && !name.trim()) return setError("Give the new project a name.");
    run(async () => {
      const id = where === "existing" ? projectId : putProject(await createProject(name)).id;
      putProject(await THINGS[kind].add(id, thing.id));
      onClose();
    });
  };

  const radio = (value, label, Icon) => (
    <label style={{ display: "flex", alignItems: "center", gap: 8, ...ui, fontSize: fs(13), color: c.heading, cursor: "pointer", marginBottom: 8 }}>
      <input
        type="radio"
        name="add-to-project-where"
        data-testid={`add-to-project-${value}`}
        checked={where === value}
        onChange={() => setWhere(value)}
        style={{ accentColor: c.amber }}
      />
      <Icon size={14} color={c.textFaint} />
      {label}
    </label>
  );

  return (
    <Modal title={`Add ${thing.name} to a project`} onClose={onClose} width={480}>
      <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, padding: 12, marginBottom: 12, background: c.panelAlt }}>
        {radio("existing", "A project you have", FolderKanban)}
        {where === "existing" && (
          <div data-testid="add-to-project-list" style={{ margin: "0 0 10px 22px", maxHeight: 220, overflowY: "auto" }}>
            {sorted.length === 0 && <div style={uiText(12, c.textFaint)}>There are no projects yet: make a new one below.</div>}
            {sorted.map((p) => {
              const already = THINGS[kind].ids(p).includes(thing.id);
              return (
                <label
                  key={p.id}
                  style={{ display: "flex", alignItems: "center", gap: 8, ...ui, fontSize: fs(13), color: already ? c.textFaint : c.textPrimary, padding: "3px 0", cursor: already ? "default" : "pointer" }}
                >
                  <input
                    type="radio"
                    name="add-to-project-id"
                    disabled={already}
                    checked={projectId === p.id}
                    onChange={() => setProjectId(p.id)}
                    style={{ accentColor: c.amber }}
                  />
                  <span style={{ overflowWrap: "anywhere" }}>{p.name}</span>
                  {already && <span style={uiText(11, c.textFaint)}>already in it</span>}
                </label>
              );
            })}
            {sorted.length > 0 && available.length === 0 && (
              <div style={uiText(12, c.textFaint, { marginTop: 4 })}>It's in every project already: make a new one below.</div>
            )}
          </div>
        )}
        {radio("new", "A new project", FolderPlus)}
        {where === "new" && (
          <div style={{ marginLeft: 22 }} onKeyDown={(e) => e.key === "Enter" && e.target.tagName === "INPUT" && submit()}>
            <TextField label="New project's name" value={name} onChange={setName} placeholder="e.g. Aquarium shop order" />
          </div>
        )}
      </div>
      <ModalActions onClose={onClose} onSubmit={submit} actionLabel="Add to project" submitting={busy} submittingLabel="Adding…" errorMsg={error} />
    </Modal>
  );
}
