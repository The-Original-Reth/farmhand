import { useState } from "react";
import { c, fs, mono, ui } from "../theme.js";
import { uiText } from "../styles.js";
import { addSourceModelVersion, createSourceModel } from "../api.js";
import { useData } from "../data.jsx";
import { useAction } from "../hooks/useAction.js";

import { ModalActions } from "../components/common/dialogs.jsx";
import { Dropzone, TextField } from "../components/common/fields.jsx";

export function UploadStlForm({ onClose }) {
  const { refresh, sourceModels } = useData();
  const [file, setFile] = useState(null);
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [choice, setChoice] = useState(null); // null = take the default; "new"; or the id of an existing model
  const { busy: submitting, error: errorMsg, setError: setErrorMsg, run } = useAction();

  const handleFile = (f) => {
    setFile(f);
    if (f && !name) setName(f.name);
  };

  // A file with the same name as a model already in the library is most likely a newer version of it
  // (the usual way to publish an update is to export over the same file name and upload it again).
  const wanted = (name.trim() || file?.name || "").toLowerCase();
  const matches = wanted
    ? sourceModels
        .filter((m) => m.name.toLowerCase() === wanted)
        .sort((x, y) => (Date.parse(y.created) || 0) - (Date.parse(x.created) || 0) || y.id - x.id)
    : [];
  const picked = choice === "new" || matches.some((m) => String(m.id) === choice) ? choice : null;
  const effective = picked ?? (matches.length ? String(matches[0].id) : "new");
  const target = matches.find((m) => String(m.id) === effective) || null;

  const handleSubmit = async () => {
    setErrorMsg(null);
    if (!file) return setErrorMsg("Choose an STL / OBJ / STEP file first.");
    if (!name.trim()) return setErrorMsg("Give it a name.");
    await run(async () => {
      if (target) await addSourceModelVersion({ modelId: target.id, file, note: note.trim() });
      else await createSourceModel({ name: name.trim(), file });
      await refresh();
      onClose();
    });
  };

  return (
    <>
      <Dropzone label="Drop a source model file here, or click to browse" file={file} onFile={handleFile} accept=".stl,.obj,.step,.stp" />
      <TextField label="Name" value={name} onChange={setName} placeholder="e.g. MMMini_NewCreature_v01.stl" />
      {matches.length > 0 && (
        <div data-testid="stl-version-choice" style={{ border: `1px solid ${c.border}`, borderRadius: 4, padding: 12, marginBottom: 14, background: c.panelAlt }}>
          <div style={uiText(12, c.textMuted, { lineHeight: 1.5, marginBottom: 8 })}>
            {matches.length === 1 ? "A model" : `${matches.length} models`} called{" "}
            <span style={{ color: c.heading }}>{matches[0].name}</span> {matches.length === 1 ? "is" : "are"} already in the
            library. Is this a newer version of {matches.length === 1 ? "it" : "one of them"}?
          </div>
          {matches.map((m) => (
            <label key={m.id} style={{ display: "flex", alignItems: "flex-start", gap: 8, ...ui, fontSize: fs(13), color: c.textPrimary, marginBottom: 6, cursor: "pointer" }}>
              <input type="radio" name="stl-version-target" checked={effective === String(m.id)} onChange={() => setChoice(String(m.id))} style={{ accentColor: c.amber, marginTop: 3 }} />
              <span>
                New version of <span style={mono}>{m.name}</span>{" "}
                <span style={{ color: c.textFaint }}>— now v{m.versions[0]?.v || 0}</span>
              </span>
            </label>
          ))}
          <label style={{ display: "flex", alignItems: "flex-start", gap: 8, ...ui, fontSize: fs(13), color: c.textPrimary, cursor: "pointer" }}>
            <input type="radio" name="stl-version-target" checked={effective === "new"} onChange={() => setChoice("new")} style={{ accentColor: c.amber, marginTop: 3 }} />
            <span>A separate model (keep it independent)</span>
          </label>
          {target && (
            <div style={uiText(11, c.textFaint, { marginTop: 8 })}>
              It becomes v{(target.versions[0]?.v || 0) + 1} and is shown above the older versions.
            </div>
          )}
        </div>
      )}
      {target && <TextField label="What changed? (optional)" value={note} onChange={setNote} placeholder="e.g. thicker legs" />}
      <ModalActions onClose={onClose} onSubmit={handleSubmit} actionLabel={target ? "Add as new version" : "Add to library"} submitting={submitting} errorMsg={errorMsg} />
    </>
  );
}
