// The STL section's Move… dialog: an STL put in another of the project's sub-components
import { useState } from "react";
import { Folder } from "lucide-react";
import { setProjectStlCounts } from "../api.js";
import { c } from "../theme.js";
import { useData } from "../data.jsx";
import { useAction } from "../hooks/useAction.js";
import { Modal, ModalActions } from "../components/common/dialogs.jsx";
import { TextField } from "../components/common/fields.jsx";
import { toolButton, uiText } from "../styles.js";
import { shown } from "./stlComponents.js";

// Moving an STL to another sub-component: one of the project's, picked, or a new one typed ("Body / Fins" for one
// inside another); left blank, it's in none
export function MoveDialog({ project, item, components, onClose }) {
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
