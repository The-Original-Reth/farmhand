import { useMemo, useState } from "react";
import { Wrench } from "lucide-react";
import { c, mono } from "../theme.js";
import { renameSubPrinter } from "../api.js";
import { useData } from "../data.jsx";
import { cancelButton, fieldBox, monoText, primaryButton, uiText } from "../styles.js";

import { ConfirmDialog, Modal } from "../components/common/dialogs.jsx";
import { nameFromParts, PrinterParts, useSubPrinterParts } from "./PrinterParts.jsx";
import { PrinterPresetPages } from "./PrinterPresetPages.jsx";

// Closing the window with changes to its parts not saved: save them, close without them, or go back to them.
// Clicking outside or the close button goes back, so nothing typed is lost by a stray click.
function SaveChanges({ sub, parts, onKeepEditing, onDiscard, onSave }) {
  return (
    <Modal title="Save the changes to its parts?" onClose={parts.saving ? () => {} : onKeepEditing} width={480}>
      <div data-testid="parts-save-ask" style={uiText(13, c.textMuted, { lineHeight: 1.6, marginBottom: 14 })}>
        You changed <span style={{ ...mono, overflowWrap: "anywhere" }}>{sub.name}</span>’s parts and haven’t saved them.
        Save them before closing?
      </div>
      {parts.saveError && <div style={uiText(12, c.danger, { marginBottom: 10, lineHeight: 1.5 })}>{parts.saveError}</div>}
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, flexWrap: "wrap" }}>
        <button onClick={onKeepEditing} disabled={parts.saving} data-testid="parts-keep-editing" style={cancelButton(parts.saving)}>
          Keep editing
        </button>
        <button onClick={onDiscard} disabled={parts.saving} data-testid="parts-discard" style={cancelButton(parts.saving)}>
          Don’t save
        </button>
        <button onClick={onSave} disabled={parts.saving} data-testid="parts-save-close" style={primaryButton(parts.saving)}>
          {parts.saving ? "Saving…" : "Save"}
        </button>
      </div>
    </Modal>
  );
}

// A sub printer's printer settings, laid out as PrusaSlicer BOSS edition's Printer Settings tab (see
// PrinterPresetPages). Farmhand only knows them from the 3MFs sliced with it, so they're read from one of
// those: the newest, or another picked from the list (the preset may have been changed between them). Read-only,
// like every setting in Farmhand.
export function SubPrinterSettings({ printer, sub, bundles, onClose }) {
  // every 3MF version sliced with it, newest first
  const sliced = useMemo(
    () =>
      bundles
        .flatMap((b) => b.versions.filter((v) => v.subPrinterId === sub.id).map((v) => ({ bundle: b, ver: v })))
        .sort((x, y) => Date.parse(y.ver.uploaded) - Date.parse(x.ver.uploaded)),
    [bundles, sub.id],
  );
  const [pickedId, setPickedId] = useState(null);
  const picked = sliced.find((s) => s.ver.id === pickedId) || sliced[0];
  const { putPrinter } = useData();
  const parts = useSubPrinterParts(printer, sub);
  // after PrusaSlicer's own pages: the parts fitted to it, written down in Farmhand
  const extraPages = [
    { id: "parts", title: "Printer parts", Icon: Wrench, render: () => <PrinterParts printer={printer} sub={sub} state={parts} /> },
  ];

  // Closing: with changes to its parts not saved, first ask whether to save them. Then, once its parts were saved, if
  // the ticked parts now make a different name, ask whether to rename it.
  const [askSave, setAskSave] = useState(false);
  const [renameTo, setRenameTo] = useState(null);
  const finishClose = (saved = parts.changed ? parts.parts : null) => {
    const proposed = saved ? nameFromParts(printer.name, saved) : null;
    if (proposed && proposed !== sub.name) setRenameTo(proposed);
    else onClose();
  };
  const requestClose = () => (parts.unsaved ? setAskSave(true) : finishClose());

  if (renameTo) {
    return (
      <ConfirmDialog
        title="Rename sub printer?"
        confirmLabel="Rename"
        cancelLabel="Keep the name"
        tone="amber"
        onClose={onClose}
        onConfirm={async () => putPrinter(await renameSubPrinter(printer.id, sub.id, renameTo))}
      >
        Its parts changed. Rename <span style={{ ...mono, overflowWrap: "anywhere" }}>{sub.name}</span> after the ticked
        parts, to <span data-testid="rename-to" style={monoText(13, c.heading, { overflowWrap: "anywhere" })}>{renameTo}</span>? Its 3MF files stay linked to it.
        Rename the preset in PrusaSlicer to match, or 3MFs sliced with the old name will add the old name back.
      </ConfirmDialog>
    );
  }

  return (
    <Modal title={`Printer Settings · ${printer.name}`} onClose={requestClose} width={960}>
      <PrinterPresetPages
        ver={picked?.ver ?? null}
        name={sub.name}
        extraPages={extraPages}
        empty={
          <div data-testid="sub-printer-no-settings" style={uiText(13, c.textMuted, { lineHeight: 1.6, marginBottom: 14 })}>
            No 3MF file sliced with <span style={mono}>{sub.name}</span> has been uploaded yet, so Farmhand doesn’t have its
            printer settings. They come from the 3MF files: upload one sliced with this preset and they’ll show here.
          </div>
        }
        from={
          picked && (
            <label style={uiText(12, c.textFaint, { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", minWidth: 0 })}>
              Settings from
              {sliced.length > 1 ? (
                <select
                  data-testid="sub-printer-settings-from"
                  value={picked.ver.id}
                  onChange={(e) => setPickedId(Number(e.target.value))}
                  style={{ ...fieldBox(), padding: "4px 8px", maxWidth: "100%" }}
                >
                  {sliced.map(({ bundle, ver }, i) => (
                    <option key={ver.id} value={ver.id}>
                      {ver.filename || bundle.name} · v{ver.v} · {ver.date}{i === 0 ? " (newest)" : ""}
                    </option>
                  ))}
                </select>
              ) : (
                <span style={monoText(12, c.textMuted)}>{picked.ver.filename || picked.bundle.name} · v{picked.ver.v}</span>
              )}
            </label>
          )
        }
      />
      {askSave && (
        // over the window, which stays as it was underneath for Keep editing
        <SaveChanges
          sub={sub}
          parts={parts}
          onKeepEditing={() => setAskSave(false)}
          onDiscard={() => finishClose()}
          onSave={async () => {
            const saved = await parts.save();
            if (saved) finishClose(saved);
          }}
        />
      )}
    </Modal>
  );
}
