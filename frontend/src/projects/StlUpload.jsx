// The STL section's Upload STL dialog: files or folders, also put in Models or kept in the project only, each in the
// sub-component its folder names
import { useState } from "react";
import { c, fs, ui } from "../theme.js";
import { useData } from "../data.jsx";
import { nameCollator } from "../lib/order.js";
import { folderPathOf } from "../components/common/fields.jsx";
import { uiText } from "../styles.js";
import { FILE_KINDS, UploadDialog } from "./ProjectFiles.jsx";
import { plural } from "../lib/format.js";
import { shown } from "./stlComponents.js";

const STL = FILE_KINDS.stl;

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
export function UploadStl({ project, onClose }) {
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
