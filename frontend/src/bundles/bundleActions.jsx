import { useRef, useState } from "react";
import { Upload } from "lucide-react";
import { c, fs, mono, ui } from "../theme.js";
import { uiText } from "../styles.js";
import { addBundleVersion, deleteBundle, inspectThreemf } from "../api.js";
import { useData } from "../data.jsx";
import { useAction } from "../hooks/useAction.js";

import { ConfirmDialog, DeleteWarning, Modal, ModalActions } from "../components/common/dialogs.jsx";
import { Dropzone } from "../components/common/fields.jsx";
import { TrashButton } from "../components/common/ui.jsx";
import { SubPrinterChoice, subPrinterFields, useSubPrinterPick } from "./SubPrinterChoice.jsx";

// The message when a 3MF or G-code was sliced for another printer than the 3MF entry's (the server says the same)
const wrongPrinter = (what, slicedFor, printerName) =>
  `Wrong printer: this ${what} was sliced for "${slicedFor}", but this 3MF belongs to "${printerName}". Slice it again ` +
  `with the "${printerName}" printer profile, or upload it as a new 3MF for "${slicedFor}".`;

// Add a newer version to an existing 3MF entry. It becomes the top version; the older ones stay below it.
function NewBundleVersionDialog({ bundle, onClose }) {
  const { refresh, printers } = useData();
  const [threemf, setThreemf] = useState(null);
  const [gcode, setGcode] = useState(null);
  const { busy: submitting, error: errorMsg, setError: setErrorMsg, run } = useAction();
  const [wrong, setWrong] = useState(null); // the dropped 3MF was sliced for another printer: why it can't be added
  const latest = useRef(null); // the 3MF dropped last: a slower look at an earlier one mustn't speak for it
  const current = bundle.versions[0]?.v || 0;
  const printer = printers.find((p) => p.id === bundle.printerId);
  const printerName = printer?.name;
  // which of the printer's printer profiles it goes to: guessed from the file's preset once it has been read
  const [preset, setPreset] = useState({ file: null, name: null, read: false });
  const sub = useSubPrinterPick(printer, preset.name, `${threemf?.name}|${preset.name}`);

  // Said as soon as the 3MF is dropped, not after it has been uploaded. The printer's name now, or any profile an
  // earlier version was sliced under (it may have been renamed since), will do. If it can't be read here, the
  // server still checks it.
  const dropThreemf = async (file) => {
    setThreemf(file);
    latest.current = file;
    setWrong(null);
    setErrorMsg(null);
    setPreset({ file, name: null, read: false });
    if (!file || !printerName) return;
    try {
      const { printerProfileName, printerPresetName } = await inspectThreemf(file);
      if (latest.current !== file) return;
      setPreset({ file, name: printerPresetName, read: true });
      const known = new Set([printerName, ...bundle.versions.map((v) => v.profile).filter(Boolean)]);
      if (printerProfileName && !known.has(printerProfileName)) setWrong(wrongPrinter("3MF", printerProfileName, printerName));
    } catch {
      /* not readable here: the upload answers for it */
    }
  };

  const handleSubmit = async () => {
    setErrorMsg(null);
    if (!threemf) return setErrorMsg("Drop the newer .3mf file first.");
    if (wrong) return setErrorMsg(wrong);
    if (sub.pick.kind === "new" && !sub.pick.name.trim()) return setErrorMsg("Give the new printer profile a name.");
    await run(async () => {
      // until the file has been read, Farmhand's own guess on the server (nothing sent)
      await addBundleVersion({ bundleId: bundle.id, threemf, gcode, subPrinter: preset.read ? subPrinterFields(sub.pick) : {} });
      await refresh();
      onClose();
    });
  };

  return (
    <>
      <div style={uiText(13, c.textMuted, { lineHeight: 1.6, marginBottom: 14 })}>
        Adds a new version to <span style={mono}>{bundle.name}</span>, which is at v{current} now. The new file becomes{" "}
        <b style={{ color: c.heading }}>v{current + 1}</b> and is shown above the older versions. It has to be sliced for the
        same printer as this entry.
      </div>
      <Dropzone label="Drop the newer .3mf file here" file={threemf} onFile={dropThreemf} accept=".3mf" />
      <Dropzone label="Drop the matching .gcode or .bgcode file here (optional)" file={gcode} onFile={setGcode} accept=".gcode,.bgcode" />
      {preset.read && !wrong && (
        <SubPrinterChoice printer={printer} presetName={preset.name} pick={sub.pick} guess={sub.guess} onChange={sub.setPick} />
      )}
      <ModalActions onClose={onClose} onSubmit={handleSubmit} actionLabel="Add new version" submitting={submitting} errorMsg={errorMsg || wrong} />
    </>
  );
}

export function NewVersionButton({ bundle }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        data-testid="new-version"
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
        title="Upload a newer version of this 3MF"
        style={{ display: "flex", alignItems: "center", gap: 5, ...ui, fontSize: fs(12), background: "none", color: c.textMuted, border: `1px solid ${c.border}`, borderRadius: 3, padding: "0 9px", height: 26, cursor: "pointer", flexShrink: 0 }}
      >
        <Upload size={12} />
        New version
      </button>
      {open && (
        <Modal title="Upload a new version" onClose={() => setOpen(false)}>
          <NewBundleVersionDialog bundle={bundle} onClose={() => setOpen(false)} />
        </Modal>
      )}
    </>
  );
}

// Delete a whole 3MF entry (every version) — the trash icon in a bundle's header
export function DeleteBundleButton({ bundle }) {
  const { refresh } = useData();
  const [open, setOpen] = useState(false);
  const monuments = bundle.versions.filter((v) => v.monument);
  return (
    <>
      <TrashButton title="Delete this 3MF and all its versions" onClick={() => setOpen(true)} />
      {open && (
        <ConfirmDialog
          title="Delete 3MF"
          onClose={() => setOpen(false)}
          onConfirm={async () => {
            await deleteBundle(bundle.id);
            await refresh();
          }}
        >
          <div>
            Permanently delete <span style={mono}>{bundle.name}</span> and{" "}
            {bundle.versions.length === 1 ? "its only version" : `all ${bundle.versions.length} of its versions`}? The
            3MF and gcode files, thumbnails and parsed settings are removed. This can't be undone.
          </div>
          {monuments.length > 0 && (
            <DeleteWarning>
              {monuments.length === 1 ? "One version is" : `${monuments.length} versions are`} flagged as a monument —
              those are meant to be kept, and will be deleted too.
            </DeleteWarning>
          )}
        </ConfirmDialog>
      )}
    </>
  );
}
