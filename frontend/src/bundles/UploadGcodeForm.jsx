import { useState } from "react";
import { c, mono } from "../theme.js";
import { errorText, uploadGcode } from "../api.js";
import { uiText } from "../styles.js";
import { useData } from "../data.jsx";

import { ModalActions } from "../components/common/dialogs.jsx";
import { Dropzone, FieldSelect } from "../components/common/fields.jsx";

// Upload a G-code for a 3MF: it goes with the 3MF's newest version (replacing a G-code that version already had),
// is shown under it, and can then be downloaded or sent to the printer. bundles: the 3MF files to choose from.
export function UploadGcodeForm({ bundles, onClose }) {
  const { printers, putBundle } = useData();
  const [bundleId, setBundleId] = useState(bundles.length === 1 ? String(bundles[0].id) : "");
  const [file, setFile] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const printerName = (b) => printers.find((p) => p.id === b.printerId)?.name || "?";
  const target = bundles.find((b) => String(b.id) === bundleId);
  const newest = target?.versions[0];

  const handleSubmit = async () => {
    setErrorMsg(null);
    if (!target) return setErrorMsg("Pick the 3MF this G-code was sliced from.");
    if (!file) return setErrorMsg("Drop the .gcode or .bgcode file first.");
    setSubmitting(true);
    try {
      putBundle(await uploadGcode(newest.id, file)); // the 3MF as it now stands
      onClose();
    } catch (e) {
      setErrorMsg(errorText(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <FieldSelect
        label="3MF file"
        placeholder="Pick the 3MF this G-code was sliced from"
        value={bundleId}
        onChange={setBundleId}
        options={bundles.map((b) => ({ value: String(b.id), label: `${printerName(b)} · ${b.name}` }))}
      />
      <Dropzone label="Drop the .gcode or .bgcode file here" file={file} onFile={setFile} accept=".gcode,.bgcode" />
      {newest && (
        <div data-testid="gcode-target" style={uiText(12, c.textFaint, { lineHeight: 1.6, marginBottom: 14 })}>
          It goes with <b style={{ color: c.heading }}>v{newest.v}</b> (<span style={mono}>{newest.filename}</span>) and is
          named after it.
          {newest.gcodeName && <> It replaces the G-code that version has now, <span style={mono}>{newest.gcodeName}</span>.</>}
        </div>
      )}
      <ModalActions onClose={onClose} onSubmit={handleSubmit} actionLabel="Upload" submitting={submitting} errorMsg={errorMsg} />
    </>
  );
}
