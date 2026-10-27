import { useState } from "react";
import { Upload } from "lucide-react";
import { c, fs, mono, ui } from "../theme.js";
import { uiText } from "../styles.js";
import { addBundleVersion, deleteBundle, errorText } from "../api.js";
import { useData } from "../data.jsx";

import { ConfirmDialog, DeleteWarning, Modal, ModalActions } from "../components/common/dialogs.jsx";
import { Dropzone } from "../components/common/fields.jsx";
import { TrashButton } from "../components/common/ui.jsx";

// Add a newer version to an existing 3MF entry. It becomes the top version; the older ones stay below it.
function NewBundleVersionDialog({ bundle, onClose }) {
  const { refresh } = useData();
  const [threemf, setThreemf] = useState(null);
  const [gcode, setGcode] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const current = bundle.versions[0]?.v || 0;

  const handleSubmit = async () => {
    setErrorMsg(null);
    if (!threemf) return setErrorMsg("Drop the newer .3mf file first.");
    setSubmitting(true);
    try {
      await addBundleVersion({ bundleId: bundle.id, threemf, gcode });
      await refresh();
      onClose();
    } catch (e) {
      setErrorMsg(errorText(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <div style={uiText(13, c.textMuted, { lineHeight: 1.6, marginBottom: 14 })}>
        Adds a new version to <span style={mono}>{bundle.name}</span>, which is at v{current} now. The new file becomes{" "}
        <b style={{ color: c.heading }}>v{current + 1}</b> and is shown above the older versions. It has to be sliced for the
        same printer as this entry.
      </div>
      <Dropzone label="Drop the newer .3mf file here" file={threemf} onFile={setThreemf} accept=".3mf" />
      <Dropzone label="Drop the matching .gcode or .bgcode file here (optional)" file={gcode} onFile={setGcode} accept=".gcode,.bgcode" />
      <ModalActions onClose={onClose} onSubmit={handleSubmit} actionLabel="Add new version" submitting={submitting} errorMsg={errorMsg} />
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
