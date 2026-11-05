import { useRef, useState } from "react";
import { c, fs, mono, ui } from "../theme.js";
import {
  addBundleVersion,
  createBundle,
  createPrinter,
  createSourceModel,
  errorText,
  inspectThreemf,
  normalizePrinter,
} from "../api.js";
import { linkButton, uiText } from "../styles.js";
import { useData } from "../data.jsx";
import { useAction } from "../hooks/useAction.js";

import { SubPrinterChoice, subPrinterFields, useSubPrinterPick } from "./SubPrinterChoice.jsx";
import { newestFirst } from "./versions.jsx";
import { ModalActions } from "../components/common/dialogs.jsx";
import { Dropzone, FieldSelect, SegmentedToggle, TextField } from "../components/common/fields.jsx";

// presetModel: when set (uploading from inside a specific STL folder), the
// source-model choice and printer field are both skipped — the bundle
// attaches to the current folder, and the printer is read from the 3MF's own
// embedded profile reference rather than asked for.
// onUploaded(the 3MF as the server answers it): called once it's uploaded (a project's page uses it to take it in)
export function Upload3mfForm({ presetModel, onClose, onUploaded }) {
  const { sourceModels, printers, bundles, modelsForBundle, refresh } = useData();
  const [mode, setMode] = useState("existing"); // "existing" | "new"
  const [newName, setNewName] = useState("");
  const [newStlFile, setNewStlFile] = useState(null);
  const [existingModelId, setExistingModelId] = useState("");
  const [threemfFile, setThreemfFile] = useState(null);
  const [gcodeFile, setGcodeFile] = useState(null);
  const { busy: submitting, error: errorMsg, setError: setErrorMsg, run } = useAction();

  // What the 3MF says about its own printer, from the backend (null until a file is dropped)
  const [inspecting, setInspecting] = useState(false);
  const [inspection, setInspection] = useState(null); // { printerProfileName, slicer, matchedPrinter }
  const [inspectError, setInspectError] = useState(null);
  const [printerChoice, setPrinterChoice] = useState("create"); // "create" | "existing"
  const [existingPrinterId, setExistingPrinterId] = useState("");
  const inspectSeq = useRef(0);
  const [versionChoice, setVersionChoice] = useState(null); // null = take the default; "new"; or the id of an entry

  // Is this a newer version of something already there? Two signals, both only on the file's own printer
  // (matched from the file, so an entry's printer lock can't object):
  //   * an entry that already has a file with THIS FILE NAME — the usual way to publish an update is to
  //     re-slice and upload under the same name, and that holds whichever model is picked below
  //   * an entry for the model being added to
  const targetModelId = presetModel ? presetModel.id : mode === "existing" && existingModelId ? Number(existingModelId) : null;
  const matchedPrinterId = inspection?.matchedPrinter?.id ?? null;
  const fileName = (threemfFile?.name || "").toLowerCase();
  const onPrinter = matchedPrinterId ? bundles.filter((b) => b.printerId === matchedPrinterId) : [];
  const byFileName = fileName ? onPrinter.filter((b) => b.versions.some((v) => (v.filename || "").toLowerCase() === fileName)).sort(newestFirst) : [];
  const byModel = targetModelId
    ? onPrinter.filter((b) => b.sourceModelIds.includes(targetModelId) && !byFileName.includes(b)).sort(newestFirst)
    : [];
  const candidates = [...byFileName, ...byModel];
  const defaultChoice = candidates.length ? String(candidates[0].id) : "new";
  const stillValid = versionChoice === "new" || candidates.some((b) => String(b.id) === versionChoice);
  const choice = stillValid && versionChoice ? versionChoice : defaultChoice;
  const versionTarget = candidates.find((b) => String(b.id) === choice) || null;

  // Decommissioned printers shouldn't be offered as a home for new files
  const selectablePrinters = printers.filter((p) => !p.decommissioned);

  // The printer the file goes to, as far as it's known yet (one about to be created has no printer profiles), and which
  // of its printer profiles: Farmhand's guess from the file's preset, until it's changed
  const targetPrinter = !inspection
    ? null
    : inspection.matchedPrinter
      ? printers.find((p) => p.id === inspection.matchedPrinter.id) || inspection.matchedPrinter
      : printerChoice === "create" && inspection.printerProfileName
        ? { name: inspection.printerProfileName, subPrinters: [] }
        : printers.find((p) => String(p.id) === existingPrinterId) || null;
  const presetName = inspection?.printerPresetName || null;
  const sub = useSubPrinterPick(targetPrinter, presetName, `${threemfFile?.name}|${targetPrinter?.id ?? targetPrinter?.name ?? ""}|${presetName}`);

  const handleThreemfFile = async (file) => {
    setThreemfFile(file);
    setInspection(null);
    setInspectError(null);
    setErrorMsg(null);
    if (!file) return;
    const seq = ++inspectSeq.current; // ignore stale results if another file is dropped meanwhile
    setInspecting(true);
    try {
      const result = await inspectThreemf(file);
      if (seq !== inspectSeq.current) return;
      setInspection(result);
      // Sensible default: create the file's printer if it has one, else pick an existing one
      setPrinterChoice(result.printerProfileName ? "create" : "existing");
      setExistingPrinterId("");
    } catch (e) {
      if (seq !== inspectSeq.current) return;
      setInspectError(errorText(e));
    } finally {
      if (seq === inspectSeq.current) setInspecting(false);
    }
  };

  const needsPrinterDecision = inspection && !inspection.matchedPrinter;
  const canCreatePrinter = !!inspection?.printerProfileName;

  const handleSubmit = async () => {
    setErrorMsg(null);
    if (!threemfFile) return setErrorMsg("Drop a .3mf file first.");
    if (inspecting) return setErrorMsg("Still reading the 3MF — one moment.");
    if (inspectError) return setErrorMsg("This 3MF couldn't be read, so it can't be uploaded.");
    if (sub.pick.kind === "new" && !sub.pick.name.trim()) return setErrorMsg("Give the new printer profile a name.");
    if (versionTarget) {
      // A newer version of an existing entry: nothing new to create, the printer is already matched
      await run(async () => {
        const out = await addBundleVersion({ bundleId: versionTarget.id, threemf: threemfFile, gcode: gcodeFile, subPrinter: subPrinterFields(sub.pick) });
        await onUploaded?.(out);
        await refresh();
        onClose();
      });
      return;
    }

    if (!presetModel) {
      if (mode === "existing" && !existingModelId) return setErrorMsg("Pick a source model.");
      if (mode === "new" && !newName.trim()) return setErrorMsg("Give the new STL folder a name.");
    }
    if (needsPrinterDecision && printerChoice === "existing" && !existingPrinterId) {
      return setErrorMsg("Pick which printer this file belongs to.");
    }

    await run(async () => {
      let sourceModelIds;
      if (presetModel) {
        sourceModelIds = [presetModel.id];
      } else if (mode === "existing") {
        sourceModelIds = [Number(existingModelId)];
      } else {
        const created = await createSourceModel({ name: newName.trim(), file: newStlFile || undefined });
        sourceModelIds = [created.id];
        // If a later step fails, a retry should reuse this folder, not create a second one
        await refresh();
        setMode("existing");
        setExistingModelId(String(created.id));
      }

      let printerId;
      if (inspection?.matchedPrinter) {
        printerId = inspection.matchedPrinter.id;
      } else if (printerChoice === "create" && canCreatePrinter) {
        // Named exactly as the file's own profile, so future uploads for it auto-match.
        // (Reuse it if an earlier attempt already created it before failing.)
        const already = printers.find((p) => p.name === inspection.printerProfileName);
        if (already) {
          printerId = already.id;
        } else {
          const printer = await createPrinter({ name: inspection.printerProfileName });
          printerId = printer.id;
          await refresh();
          setInspection((prev) => ({ ...prev, matchedPrinter: normalizePrinter(printer) }));
        }
      } else {
        printerId = Number(existingPrinterId);
      }

      const out = await createBundle({ sourceModelIds, threemf: threemfFile, gcode: gcodeFile, printerId, subPrinter: subPrinterFields(sub.pick) });
      await onUploaded?.(out);
      await refresh();
      onClose();
    });
  };

  return (
    <>
      <Dropzone label="Drop the .3mf file here" file={threemfFile} onFile={handleThreemfFile} accept=".3mf" />
      <Dropzone label="Drop the matching .gcode or .bgcode file here (optional)" file={gcodeFile} onFile={setGcodeFile} accept=".gcode,.bgcode" />

      {/* Printer — read from the file, with a way out when it isn't registered */}
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

      {targetPrinter && (
        <SubPrinterChoice printer={targetPrinter} presetName={presetName} pick={sub.pick} guess={sub.guess} onChange={sub.setPick} />
      )}

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

      {candidates.length > 0 && (
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
      )}

      <ModalActions
        onClose={onClose}
        onSubmit={handleSubmit}
        actionLabel={versionTarget ? "Add as new version" : "Upload"}
        submitting={submitting || inspecting}
        errorMsg={errorMsg}
      />
    </>
  );
}
