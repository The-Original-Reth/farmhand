import { useMemo, useState } from "react";
import { Check, Copy, Layers3, Pencil, Plus, Star, Wrench, X } from "lucide-react";
import { c, fs, mono } from "../theme.js";
import { addSubPrinter, copySubPrinter, deleteSubPrinter, errorText, renameSubPrinter, setDefaultSubPrinter } from "../api.js";
import { useData } from "../data.jsx";
import { cancelButton, fieldBox, headerButton, linkButton, monoText, primaryButton, uiText } from "../styles.js";

import { ConfirmDialog, Modal } from "../components/common/dialogs.jsx";
import { SectionLabel, TrashButton } from "../components/common/ui.jsx";
import { nameFromParts, PrinterParts, useSubPrinterParts } from "./PrinterParts.jsx";
import { PrinterPresetPages } from "./PrinterPresetPages.jsx";

// The 3MFs on a printer sliced with one of its sub printers (any of their versions)
export const usesSubPrinter = (bundle, subPrinterId) => bundle.versions.some((v) => v.subPrinterId === subPrinterId);

// A sub printer's name, for a version that names one (null when it names none, or it was removed)
export const subPrinterName = (printers, bundle, ver) =>
  ver.subPrinterId == null
    ? null
    : printers.find((p) => p.id === bundle.printerId)?.subPrinters.find((s) => s.id === ver.subPrinterId)?.name ?? null;

// The name a copy of `name` starts with: "<name> - copy", or "- copy 2", 3... when the printer has that one already
// (as the API names it when given none)
const copyName = (printer, name) => {
  for (let n = 1; ; n++) {
    const tail = n === 1 ? " - copy" : ` - copy ${n}`;
    const candidate = name.slice(0, 120 - tail.length).trimEnd() + tail;
    if (!printer.subPrinters.some((s) => s.name === candidate)) return candidate;
  }
};

// The box a name is typed into, with Enter to save and Escape to cancel
function NameInput({ value, onChange, onEnter, onEscape, placeholder, testId, disabled }) {
  return (
    <input
      autoFocus
      data-testid={testId}
      value={value}
      disabled={disabled}
      placeholder={placeholder}
      aria-label={placeholder}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter") onEnter();
        if (e.key === "Escape") onEscape();
      }}
      style={{ ...fieldBox(), ...mono, fontSize: fs(12), padding: "4px 8px", flex: "1 1 220px", minWidth: 0 }}
    />
  );
}

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
function SubPrinterSettings({ printer, sub, bundles, onClose }) {
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

// One sub printer: its name (click for its printer settings; renamed in place), how many 3MFs were sliced with it (click
// to show only those), a star to make it the default (the one the printer's uploads start on), Copy (a new one with its
// parts, named "<name> - copy" unless that's changed), Remove
function SubPrinterRow({ printer, sub, bundles, count, active, onFilter }) {
  const { putPrinter } = useData();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(sub.name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [removeOpen, setRemoveOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [copyAs, setCopyAs] = useState(null); // the copy's name while it's being made, else null
  const isDefault = printer.defaultSubPrinterId === sub.id;

  const toggleDefault = async () => {
    setBusy(true);
    setError(null);
    try {
      putPrinter(await setDefaultSubPrinter(printer.id, isDefault ? null : sub.id));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (text.trim() === sub.name) return setEditing(false);
    setBusy(true);
    setError(null);
    try {
      putPrinter(await renameSubPrinter(printer.id, sub.id, text));
      setEditing(false);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const makeCopy = async () => {
    if (!copyAs.trim()) return;
    setBusy(true);
    setError(null);
    try {
      putPrinter(await copySubPrinter(printer.id, sub.id, copyAs));
      setCopyAs(null);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const closeCopy = () => {
    setCopyAs(null);
    setError(null);
  };

  const iconButton = { ...headerButton(), padding: "0 7px" };
  return (
    <div data-testid="sub-printer" style={{ padding: "8px 12px", borderTop: `1px solid ${c.border}` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <Layers3 size={13} color={c.textFaint} />
        {editing ? (
          <>
            <NameInput value={text} onChange={setText} onEnter={save} onEscape={() => setEditing(false)} placeholder="Sub printer name" testId="sub-printer-name-input" disabled={busy} />
            <button onClick={save} disabled={busy} title="Save the name" style={iconButton}><Check size={13} /></button>
            <button onClick={() => { setEditing(false); setError(null); }} disabled={busy} title="Cancel" style={iconButton}><X size={13} /></button>
          </>
        ) : (
          <>
            <span style={{ flex: "1 1 220px", minWidth: 0, display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
              <button
                onClick={() => setSettingsOpen(true)}
                data-testid="sub-printer-name"
                title="Show its printer settings"
                style={{
                  ...monoText(12, c.heading, { minWidth: 0, overflowWrap: "anywhere" }),
                  background: "none", border: "none", padding: 0, textAlign: "left", cursor: "pointer", textDecoration: "underline dotted",
                }}
              >
                {sub.name}
              </button>
              {isDefault && (
                <span data-testid="sub-printer-default" style={uiText(11, c.amber, { fontWeight: 600 })}>default</span>
              )}
            </span>
            <button
              onClick={() => onFilter(active ? null : sub.id)}
              disabled={count === 0}
              aria-pressed={active}
              data-testid="sub-printer-filter"
              title={count === 0 ? "No 3MF files were sliced with it yet" : active ? "Show every 3MF file again" : "Show only the 3MF files sliced with it"}
              style={{
                ...headerButton(), cursor: count === 0 ? "default" : "pointer",
                ...(active && { color: c.amber, border: `1px solid ${c.amber}`, background: c.amberDim }),
              }}
            >
              {count} x .3MF
            </button>
            <button
              onClick={toggleDefault}
              disabled={busy}
              aria-pressed={isDefault}
              data-testid="sub-printer-star"
              title={isDefault ? `The default: ${printer.name}’s uploads start on it. Click to have no default` : `Make it the default: ${printer.name}’s uploads start on it`}
              style={{ ...iconButton, ...(isDefault && { color: c.amber, border: `1px solid ${c.amber}` }) }}
            >
              <Star size={12} fill={isDefault ? c.amber : "none"} />
            </button>
            <button onClick={() => { setText(sub.name); setEditing(true); }} title="Rename" style={iconButton}><Pencil size={12} /></button>
            <button
              onClick={() => { setError(null); setCopyAs(copyName(printer, sub.name)); }}
              data-testid="sub-printer-copy"
              title="Make a copy, with its parts"
              aria-label={`Copy ${sub.name}`}
              style={iconButton}
            >
              <Copy size={12} />
            </button>
            <TrashButton title="Remove this sub printer" onClick={() => setRemoveOpen(true)} />
          </>
        )}
      </div>
      {copyAs != null && (
        <div data-testid="sub-printer-copy-form" style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginTop: 8, paddingLeft: 23 }}>
          <span style={uiText(12, c.textMuted)}>Copy as</span>
          <NameInput value={copyAs} onChange={setCopyAs} onEnter={makeCopy} onEscape={closeCopy} placeholder="The copy’s name" testId="sub-printer-copy-input" disabled={busy} />
          <button onClick={makeCopy} disabled={busy || !copyAs.trim()} data-testid="sub-printer-copy-save" style={headerButton()}>
            {busy ? "Copying…" : "Copy"}
          </button>
          <button onClick={closeCopy} disabled={busy} style={linkButton(12)}>Cancel</button>
          <div style={uiText(11, c.textFaint, { flexBasis: "100%", lineHeight: 1.5 })}>
            A new sub printer with the same parts. Its 3MF files{isDefault ? " and being the default" : ""} stay with {sub.name}.
          </div>
        </div>
      )}
      {error && <div style={uiText(12, c.danger, { marginTop: 6, paddingLeft: 23 })}>{error}</div>}
      {settingsOpen && <SubPrinterSettings printer={printer} sub={sub} bundles={bundles} onClose={() => setSettingsOpen(false)} />}
      {removeOpen && (
        <ConfirmDialog
          title="Remove sub printer"
          confirmLabel="Remove"
          onClose={() => setRemoveOpen(false)}
          onConfirm={async () => {
            if (active) onFilter(null);
            putPrinter(await deleteSubPrinter(printer.id, sub.id));
          }}
        >
          Remove <span style={mono}>{sub.name}</span> from <b style={{ color: c.heading }}>{printer.name}</b>?{" "}
          {count > 0
            ? `Its ${count} 3MF file${count === 1 ? " stays" : "s stay"}, with no sub printer.`
            : "No 3MF files were sliced with it."}{" "}
          The parts written down for it on its Printer parts page are removed too.{isDefault && " It’s the default, so there will be no default."} A 3MF uploaded later that was sliced
          with it adds it again.
        </ConfirmDialog>
      )}
    </div>
  );
}

// A printer's sub printers: its printer presets in PrusaSlicer (the ones listed under it in the Printers tab). They're
// added when a 3MF sliced with one is uploaded, and can be added, renamed and removed here. `filter` is the one whose
// 3MFs are the only ones shown below (null: all of them).
export function SubPrinters({ printer, bundles, filter, onFilter }) {
  const { putPrinter } = useData();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const add = async () => {
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      putPrinter(await addSubPrinter(printer.id, name));
      setName("");
      setAdding(false);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const close = () => {
    setAdding(false);
    setName("");
    setError(null);
  };

  return (
    <div data-testid="sub-printers">
      <SectionLabel>Sub printers: its printer presets in PrusaSlicer</SectionLabel>
      <div style={{ border: `1px solid ${c.border}`, borderRadius: 4, background: c.panel }}>
        {printer.subPrinters.length === 0 && (
          <div style={uiText(13, c.textFaint, { padding: "10px 12px", lineHeight: 1.6 })}>
            None yet. One is added when a 3MF sliced with one of {printer.name}’s presets is uploaded, or add one here.
          </div>
        )}
        <div style={{ marginTop: -1 }}>
          {printer.subPrinters.map((s) => (
            <SubPrinterRow
              key={s.id}
              printer={printer}
              sub={s}
              bundles={bundles}
              count={bundles.filter((b) => usesSubPrinter(b, s.id)).length}
              active={filter === s.id}
              onFilter={onFilter}
            />
          ))}
        </div>
        <div style={{ padding: "8px 12px", borderTop: `1px solid ${c.border}` }}>
          {adding ? (
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <NameInput value={name} onChange={setName} onEnter={add} onEscape={close} placeholder="The preset’s name, as PrusaSlicer shows it" testId="sub-printer-add-input" disabled={busy} />
              <button onClick={add} disabled={busy || !name.trim()} data-testid="sub-printer-add-save" style={headerButton()}>
                {busy ? "Adding…" : "Add"}
              </button>
              <button onClick={close} disabled={busy} style={linkButton(12)}>Cancel</button>
            </div>
          ) : (
            <button onClick={() => setAdding(true)} data-testid="sub-printer-add" style={headerButton()}>
              <Plus size={12} /> Add sub printer
            </button>
          )}
          {error && <div style={uiText(12, c.danger, { marginTop: 6 })}>{error}</div>}
        </div>
      </div>
    </div>
  );
}
