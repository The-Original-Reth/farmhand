import { c, fs, mono, ui } from "../theme.js";
import { linkButton, uiText } from "../styles.js";
import { useData } from "../data.jsx";
import { Dropzone, FieldSelect, SegmentedToggle, TextField } from "../components/common/fields.jsx";

// The parts of the Upload 3MF form (Upload3mfForm.jsx), which keeps their state.

// The printer the 3MF is for: read from the file, with a way out when it isn't registered
export function PrinterFromFile({
  inspecting, inspectError, inspection, printerChoice, setPrinterChoice, existingPrinterId, setExistingPrinterId,
}) {
  const { printers } = useData();
  // Decommissioned printers shouldn't be offered as a home for new files
  const selectablePrinters = printers.filter((p) => !p.decommissioned);
  const needsPrinterDecision = inspection && !inspection.matchedPrinter;
  const canCreatePrinter = !!inspection?.printerProfileName;
  return (
    <>
      {inspecting && (
        <div style={uiText(12, c.textFaint, { marginBottom: 14 })}>Reading the 3MF…</div>
      )}
      {inspectError && (
        <div style={uiText(12, c.amber, { marginBottom: 14, lineHeight: 1.5 })}>
          Couldn't read this 3MF: {inspectError}
        </div>
      )}
      {inspection?.matchedPrinter && (
        <div style={uiText(12, c.textFaint, { marginBottom: 14 })}>
          Printer: <span style={{ color: c.heading }}>{inspection.matchedPrinter.name}</span> — detected from the file.
        </div>
      )}
      {needsPrinterDecision && (
        <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, padding: 12, marginBottom: 14, background: c.panelAlt }}>
          <div style={uiText(12, c.textMuted, { marginBottom: 10, lineHeight: 1.5 })}>
            {canCreatePrinter ? (
              <>
                This file was sliced for <span style={{ color: c.heading }}>“{inspection.printerProfileName}”</span>, which
                isn't registered yet.
              </>
            ) : (
              <>This file doesn't say which printer it was sliced for.</>
            )}
          </div>

          {canCreatePrinter && selectablePrinters.length > 0 && (
            <SegmentedToggle
              value={printerChoice}
              onChange={setPrinterChoice}
              options={[
                { value: "create", label: `Create “${inspection.printerProfileName}”` },
                { value: "existing", label: "Use an existing printer" },
              ]}
            />
          )}

          {canCreatePrinter && printerChoice === "create" && (
            <div style={uiText(11, c.textFaint, { lineHeight: 1.5 })}>
              A printer named exactly “{inspection.printerProfileName}” will be added to the registry, and this file
              will be locked to it. You can fill in its type and IP addresses later.
            </div>
          )}

          {(printerChoice === "existing" || !canCreatePrinter) &&
            (selectablePrinters.length > 0 ? (
              <FieldSelect
                label="Printer"
                placeholder="Select a printer…"
                value={existingPrinterId}
                onChange={setExistingPrinterId}
                options={selectablePrinters.map((p) => ({ value: String(p.id), label: p.name }))}
              />
            ) : (
              <div style={uiText(12, c.amber, { lineHeight: 1.5 })}>
                There are no registered printers to choose from yet — add one under Printers first.
              </div>
            ))}
        </div>
      )}
    </>
  );
}

// Which model it's added to: the one whose page it's uploaded from, or an existing or new STL folder
export function SourceModelChoice({
  presetModel, mode, setMode, existingModelId, setExistingModelId, newName, setNewName, newStlFile, setNewStlFile,
}) {
  const { sourceModels } = useData();
  return (
    <>
      {presetModel ? (
        <div style={uiText(12, c.textFaint, { marginBottom: 14 })}>
          Adding to <span style={{ color: c.heading }}>{presetModel.name}</span>.
        </div>
      ) : (
        <>
          <SegmentedToggle
            value={mode}
            onChange={setMode}
            options={[
              { value: "existing", label: "Existing STL folder" },
              { value: "new", label: "New STL folder" },
            ]}
          />
          {mode === "existing" ? (
            <FieldSelect
              label="Source model"
              placeholder="Select a source model…"
              value={existingModelId}
              onChange={setExistingModelId}
              options={sourceModels.map((m) => ({ value: String(m.id), label: m.name }))}
            />
          ) : (
            <>
              <TextField
                label="New STL folder name"
                value={newName}
                onChange={setNewName}
                placeholder="e.g. MMMini_NewCreature_v01.stl"
              />
              {sourceModels.some((m) => m.name.toLowerCase() === newName.trim().toLowerCase()) && newName.trim() && (
                <div data-testid="folder-exists" style={uiText(12, c.amber, { lineHeight: 1.5, marginTop: -6, marginBottom: 14 })}>
                  A folder called “{newName.trim()}” already exists.{" "}
                  <button
                    onClick={() => {
                      const existing = sourceModels.find((m) => m.name.toLowerCase() === newName.trim().toLowerCase());
                      setMode("existing");
                      setExistingModelId(String(existing.id));
                    }}
                    style={linkButton(12)}
                  >
                    Use that folder instead
                  </button>
                </div>
              )}
              <Dropzone
                label="Optionally drop the STL / OBJ / STEP file here — the folder can be created without one"
                compact
                file={newStlFile}
                onFile={setNewStlFile}
                accept=".stl,.obj,.step,.stp"
              />
            </>
          )}
        </>
      )}
    </>
  );
}

// Whether it's a newer version of a 3MF already on its printer (candidates), or a separate 3MF
export function VersionChoice({ candidates, byFileName, inspection, choice, setVersionChoice, versionTarget, presetModel }) {
  const { modelsForBundle } = useData();
  if (!candidates.length) return null;
  return (
    <div data-testid="version-choice" style={{ border: `1px solid ${c.border}`, borderRadius: 4, padding: 12, marginBottom: 14, background: c.panelAlt }}>
      <div style={uiText(12, c.textMuted, { lineHeight: 1.5, marginBottom: 8 })}>
        {byFileName.length > 0 ? (
          <>
            <span style={{ color: c.heading }}>{inspection.matchedPrinter.name}</span> already has{" "}
            {byFileName.length === 1 ? "a 3MF" : `${byFileName.length} 3MF files`} with this file name.
          </>
        ) : (
          <>
            This model already has {candidates.length === 1 ? "a 3MF" : `${candidates.length} 3MF files`} on{" "}
            <span style={{ color: c.heading }}>{inspection.matchedPrinter.name}</span>.
          </>
        )}{" "}
        Is this file a newer version of {candidates.length === 1 ? "it" : "one of them"}?
      </div>
      {candidates.map((b) => (
        <label key={b.id} style={{ display: "flex", alignItems: "flex-start", gap: 8, ...ui, fontSize: fs(13), color: c.textPrimary, marginBottom: 6, cursor: "pointer" }}>
          <input type="radio" name="version-target" checked={choice === String(b.id)} onChange={() => setVersionChoice(String(b.id))} style={{ accentColor: c.amber, marginTop: 3 }} />
          <span>
            New version of <span style={mono}>{b.name}</span>{" "}
            <span style={{ color: c.textFaint }}>
              — now v{b.versions[0]?.v}
              {!presetModel && modelsForBundle(b).length > 0 ? `, on ${modelsForBundle(b).map((m) => m.name).join(", ")}` : ""}
            </span>
          </span>
        </label>
      ))}
      <label style={{ display: "flex", alignItems: "flex-start", gap: 8, ...ui, fontSize: fs(13), color: c.textPrimary, cursor: "pointer" }}>
        <input type="radio" name="version-target" checked={choice === "new"} onChange={() => setVersionChoice("new")} style={{ accentColor: c.amber, marginTop: 3 }} />
        <span>A separate 3MF (keep it independent of the others)</span>
      </label>
      {versionTarget && (
        <div style={uiText(11, c.textFaint, { marginTop: 8 })}>
          It becomes v{(versionTarget.versions[0]?.v || 0) + 1} and is shown above the older versions.
        </div>
      )}
    </div>
  );
}
