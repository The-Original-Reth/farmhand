// The STL section's Add from Models dialog
import { addProjectModel } from "../api.js";
import { useData } from "../data.jsx";
import { PickDialog } from "./pieces.jsx";
import { plural } from "../lib/format.js";

// Picking models from the Models page to use: every model not in the project yet
export function AddFromModels({ project, onClose }) {
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
