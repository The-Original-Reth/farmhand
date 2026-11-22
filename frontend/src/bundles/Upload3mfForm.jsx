import { useRef, useState } from "react";
import {
  addBundleVersion,
  createBundle,
  createPrinter,
  createSourceModel,
  errorText,
  inspectThreemf,
  normalizePrinter,
} from "../api.js";
import { useData } from "../data.jsx";
import { useAction } from "../hooks/useAction.js";

import { SubPrinterChoice, subPrinterFields, useSubPrinterPick } from "./SubPrinterChoice.jsx";
import { newestFirst } from "./versions.jsx";
import { ModalActions } from "../components/common/dialogs.jsx";
import { Dropzone } from "../components/common/fields.jsx";
import { PrinterFromFile, SourceModelChoice, VersionChoice } from "./Upload3mfParts.jsx";

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
      <PrinterFromFile
        inspecting={inspecting} inspectError={inspectError} inspection={inspection}
        printerChoice={printerChoice} setPrinterChoice={setPrinterChoice}
        existingPrinterId={existingPrinterId} setExistingPrinterId={setExistingPrinterId}
      />

      {targetPrinter && (
        <SubPrinterChoice printer={targetPrinter} presetName={presetName} pick={sub.pick} guess={sub.guess} onChange={sub.setPick} />
      )}

      <SourceModelChoice
        presetModel={presetModel} mode={mode} setMode={setMode} existingModelId={existingModelId}
        setExistingModelId={setExistingModelId} newName={newName} setNewName={setNewName}
        newStlFile={newStlFile} setNewStlFile={setNewStlFile}
      />

      <VersionChoice
        candidates={candidates} byFileName={byFileName} inspection={inspection} choice={choice}
        setVersionChoice={setVersionChoice} versionTarget={versionTarget} presetModel={presetModel}
      />

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
