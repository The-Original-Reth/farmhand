import { useState } from "react";
import { Trash2 } from "lucide-react";
import { c, fs, mono } from "../theme.js";
import { toolButton, uiText } from "../styles.js";
import { addSourceModelVersion, deleteSourceModel } from "../api.js";
import { useData } from "../data.jsx";
import { useAction } from "../hooks/useAction.js";

import { ConfirmDialog, DeleteWarning, ModalActions } from "../components/common/dialogs.jsx";
import { Dropzone, TextField } from "../components/common/fields.jsx";

// Delete a whole STL folder
export function DeleteModelButton({ model, onDeleted }) {
  const { bundlesForModel, refresh } = useData();
  const [open, setOpen] = useState(false);
  const related = bundlesForModel(model.id);
  const exclusive = related.filter((b) => b.sourceModelIds.length === 1); // sliced only from this model
  const shared = related.filter((b) => b.sourceModelIds.length > 1); // mixed plates that also use other models
  return (
    <>
      <button
        onClick={() => setOpen(true)}
        style={toolButton(12, { marginBottom: 10 })}
      >
        <Trash2 size={12} />
        Delete folder
      </button>
      {open && (
        <ConfirmDialog
          title="Delete STL folder"
          confirmLabel={exclusive.length > 0 ? "Delete folder and 3MF files" : "Delete folder"}
          onClose={() => setOpen(false)}
          onConfirm={async () => {
            await deleteSourceModel(model.id, { cascade: exclusive.length > 0 });
            onDeleted?.();
            await refresh();
          }}
        >
          <div>
            Permanently delete <span style={mono}>{model.name}</span>
            {model.versions.length > 0
              ? ` and ${model.versions.length === 1 ? "its file" : `all ${model.versions.length} versions of its file`}`
              : ""}
            ? This can't be undone.
          </div>
          {exclusive.length > 0 && (
            <DeleteWarning>
              This will also permanently delete {exclusive.length === 1 ? "this 3MF" : `these ${exclusive.length} 3MFs`},
              which {exclusive.length === 1 ? "was" : "were"} sliced only from this model:
              <div style={{ ...mono, fontSize: fs(11), marginTop: 6, color: c.textMuted, lineHeight: 1.7 }}>
                {exclusive.map((b) => (
                  <div key={b.id}>{b.name}</div>
                ))}
              </div>
            </DeleteWarning>
          )}
          {shared.length > 0 && (
            <div style={{ marginTop: 8 }}>
              {shared.length === 1 ? "1 other 3MF is a mixed plate" : `${shared.length} other 3MFs are mixed plates`} that
              also use other models. {shared.length === 1 ? "It's" : "They're"} kept, just no longer linked to this one.
            </div>
          )}
        </ConfirmDialog>
      )}
    </>
  );
}

// Add a file to an STL folder that has none (e.g. created empty, or its only version was deleted)
export function AddModelFileForm({ model, isNewVersion = false, onClose }) {
  const { refresh } = useData();
  const [file, setFile] = useState(null);
  const [note, setNote] = useState("");
  const { busy: submitting, error: errorMsg, setError: setErrorMsg, run } = useAction();

  const handleSubmit = async () => {
    setErrorMsg(null);
    if (!file) return setErrorMsg("Choose an STL / OBJ / STEP file first.");
    await run(async () => {
      await addSourceModelVersion({ modelId: model.id, file, note: note.trim() });
      await refresh();
      onClose();
    });
  };

  return (
    <>
      {isNewVersion && (
        <div style={uiText(13, c.textMuted, { lineHeight: 1.6, marginBottom: 14 })}>
          Adds a new version of <span style={mono}>{model.name}</span>. It becomes{" "}
          <b style={{ color: c.heading }}>v{(model.versions[0]?.v || 0) + 1}</b> and is shown above the older versions.
        </div>
      )}
      <Dropzone
        label={isNewVersion ? "Drop the newer STL / OBJ / STEP file here" : "Drop an STL / OBJ / STEP file here"}
        file={file}
        onFile={setFile}
        accept=".stl,.obj,.step,.stp"
      />
      <TextField label="What changed? (optional)" value={note} onChange={setNote} placeholder="e.g. thicker legs" />
      <ModalActions onClose={onClose} onSubmit={handleSubmit} actionLabel={isNewVersion ? "Upload version" : "Add file"} submitting={submitting} errorMsg={errorMsg} />
    </>
  );
}
