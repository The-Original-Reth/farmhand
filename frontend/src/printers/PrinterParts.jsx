import { useEffect, useState } from "react";
import { Pencil, Plus } from "lucide-react";
import { c, fs, mono } from "../theme.js";
import { addSubPrinterPart, deleteSubPrinterPart, errorText, getSubPrinterParts, updateSubPrinterPart } from "../api.js";
import { fieldBox, headerButton, linkButton, monoText, primaryButton, uiText } from "../styles.js";

import { ConfirmDialog } from "../components/common/dialogs.jsx";
import { TrashButton } from "../components/common/ui.jsx";

// A sub printer's Printer parts page, in its Printer Settings window: the parts fitted to it, written down by hand
// (what it is, who makes it, its model, when it was fitted, a note). Kept in Farmhand, not in the 3MFs. Each part
// can be ticked "Add to name": the ticked parts' models make the name the sub printer can be renamed to when the
// window closes (nameFromParts).

const EMPTY = { part: "", make: "", model: "", installedOn: "", note: "", inName: false };
const COLUMNS = "56px minmax(90px, 1fr) minmax(90px, 1fr) minmax(110px, 1.3fr) 110px minmax(130px, 1.7fr) 64px";
const fmtDate = (iso) =>
  iso ? new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" }) : "—";

// The parts every sub printer starts with (the API's DEFAULT_PARTS): their names can't be changed
const DEFAULT_PART_NAMES = new Set(["Toolhead", "Hotend", "Nozzle", "Extruder", "Gantry", "XY motor"]);

// A gantry only goes into the name when it's an AWD / 4WD / quad motor one
const isGantry = (p) => p.part.trim().toLowerCase() === "gantry";
const saysAwd = (p) => /\b(awd|4wd|quad)\b/i.test(`${p.make} ${p.model}`);
const counts = (p) => p.inName && p.model.trim() && (!isGantry(p) || saysAwd(p));

// The name the ticked parts make: the printer's name without spaces, then each ticked part's model in list order,
// with spaces as underscores: "VT1190_Stealthburner_Rapido_UHF_0.5_WC_Galileo_2". null when no part counts.
export function nameFromParts(printerName, parts) {
  const pieces = (parts || []).filter(counts).map((p) => p.model.trim().replace(/\s+/g, "_"));
  if (!pieces.length) return null;
  return [printerName.replace(/\s+/g, ""), ...pieces].join("_").slice(0, 120);
}

// The window's hold on a sub printer's parts: loaded once when it opens (so they survive moving between its pages),
// and `changed` once anything was added, changed, ticked or removed.
export function useSubPrinterParts(printer, sub) {
  const [parts, setParts] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [changed, setChanged] = useState(false);
  useEffect(() => {
    let cancelled = false;
    getSubPrinterParts(printer.id, sub.id)
      .then((list) => !cancelled && setParts(list))
      .catch((e) => !cancelled && setLoadError(errorText(e)));
    return () => {
      cancelled = true;
    };
  }, [printer.id, sub.id]);
  const update = (list) => {
    setParts(list);
    setChanged(true);
  };
  return { parts, loadError, changed, update };
}

// The five boxes a part is written in, with Save and Cancel (adding a new one, or changing one)
function PartForm({ initial, saveLabel, onSave, onCancel }) {
  const lockedName = DEFAULT_PART_NAMES.has(initial.part); // a default part keeps its name
  const [fields, setFields] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (name) => (e) => setFields((f) => ({ ...f, [name]: e.target.value }));
  const box = { ...fieldBox(), fontSize: fs(12), padding: "4px 8px", minWidth: 0, width: "100%", boxSizing: "border-box" };

  const save = async () => {
    if (!fields.part.trim()) return setError("Say what the part is (e.g. Hotend)");
    setBusy(true);
    setError(null);
    try {
      await onSave(fields);
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  };
  const keys = (e) => {
    if (e.key === "Enter" && e.target.tagName !== "TEXTAREA") save();
    if (e.key === "Escape") {
      e.stopPropagation(); // closes this form, not the window
      onCancel();
    }
  };

  return (
    <div data-testid="part-form" onKeyDown={keys} style={{ padding: "8px 0", borderTop: `1px solid ${c.border}` }}>
      <div style={{ display: "grid", gridTemplateColumns: COLUMNS, gap: 8, alignItems: "start" }}>
        <span style={{ display: "flex", justifyContent: "center", paddingTop: 5 }}>
          <input type="checkbox" checked={!!fields.inName} onChange={(e) => setFields((f) => ({ ...f, inName: e.target.checked }))} aria-label="Add to name" data-testid="part-in-name-box" disabled={busy} style={{ margin: 0, accentColor: c.amber }} />
        </span>
        {lockedName ? (
          <span data-testid="part-part-locked" title="One of the default parts: its name can't be changed" style={uiText(13, c.heading, { paddingTop: 4 })}>
            {fields.part}
          </span>
        ) : (
          <input autoFocus value={fields.part} onChange={set("part")} placeholder="Part (e.g. Hotend)" aria-label="Part" data-testid="part-part" style={box} disabled={busy} />
        )}
        <input autoFocus={lockedName} value={fields.make} onChange={set("make")} placeholder="Make" aria-label="Make" data-testid="part-make" style={box} disabled={busy} />
        <input value={fields.model} onChange={set("model")} placeholder="Model" aria-label="Model" data-testid="part-model" style={{ ...box, ...mono }} disabled={busy} />
        <input type="date" value={fields.installedOn || ""} onChange={set("installedOn")} aria-label="Installed on" data-testid="part-installed" style={box} disabled={busy} />
        <input value={fields.note} onChange={set("note")} placeholder="Note" aria-label="Note" data-testid="part-note" style={box} disabled={busy} />
        <span />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8 }}>
        <button onClick={save} disabled={busy} data-testid="part-save" style={{ ...primaryButton(busy), fontSize: fs(12), padding: "5px 12px" }}>
          {busy ? "Saving…" : saveLabel}
        </button>
        <button onClick={onCancel} disabled={busy} style={linkButton(12)}>Cancel</button>
        {error && <span style={uiText(12, c.danger)}>{error}</span>}
      </div>
    </div>
  );
}

// Why a ticked part isn't in the name (or null when it is, or isn't ticked)
const leftOut = (p) => {
  if (!p.inName) return null;
  if (!p.model.trim()) return "no model yet, so it isn’t in the name";
  if (isGantry(p) && !saysAwd(p)) return "only in the name when its make or model says AWD, 4WD or quad";
  return null;
};

// `state` is the window's useSubPrinterParts
export function PrinterParts({ printer, sub, state }) {
  const { parts, loadError, update } = state;
  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [removing, setRemoving] = useState(null); // the part asked about in the Remove dialog
  const [tickError, setTickError] = useState(null);

  if (loadError) return <div style={uiText(13, c.amber)}>Couldn't load its parts: {loadError}</div>;
  if (!parts) return <div style={uiText(13, c.textFaint)}>Loading parts…</div>;

  const toggle = async (p) => {
    setTickError(null);
    try {
      update(await updateSubPrinterPart(printer.id, sub.id, p.id, { ...p, inName: !p.inName }));
    } catch (e) {
      setTickError(errorText(e));
    }
  };
  const proposed = nameFromParts(printer.name, parts);

  return (
    <fieldset data-testid="printer-parts" style={{ border: `1px solid ${c.border}`, borderRadius: 4, padding: "6px 14px 12px", margin: 0, minWidth: 0 }}>
      <legend style={uiText(13, c.heading, { fontWeight: 600, padding: "0 6px" })}>Printer parts</legend>
      <div style={uiText(12, c.textFaint, { marginBottom: 10, lineHeight: 1.5 })}>
        The parts fitted to <span style={mono}>{sub.name}</span>. Written down here and kept in Farmhand (and its settings
        copy); the 3MF files don’t carry them. Tick <b>Add to name</b> to put a part’s model in the sub printer’s name:
        when you close this window after changing its parts, you’re asked whether to rename it.
      </div>
      <div style={{ display: "grid", gridTemplateColumns: COLUMNS, gap: 8, padding: "0 0 6px", alignItems: "end" }}>
        {["Add to name", "Part", "Make", "Model", "Installed", "Note", ""].map((h, i) => (
          <span key={i} style={uiText(11, c.textFaint, i === 0 ? { textAlign: "center", lineHeight: 1.2 } : undefined)}>{h}</span>
        ))}
      </div>
      {parts.length === 0 && !adding && (
        <div style={uiText(13, c.textFaint, { padding: "10px 0", borderTop: `1px solid ${c.border}` })}>No parts written down yet.</div>
      )}
      {parts.map((p) =>
        editingId === p.id ? (
          <PartForm
            key={p.id}
            initial={{ part: p.part, make: p.make, model: p.model, installedOn: p.installedOn || "", note: p.note, inName: p.inName }}
            saveLabel="Save"
            onCancel={() => setEditingId(null)}
            onSave={async (fields) => {
              update(await updateSubPrinterPart(printer.id, sub.id, p.id, fields));
              setEditingId(null);
            }}
          />
        ) : (
          <div key={p.id} data-testid="printer-part" style={{ padding: "7px 0", borderTop: `1px solid ${c.border}` }}>
            <div style={{ display: "grid", gridTemplateColumns: COLUMNS, gap: 8, alignItems: "center" }}>
              <span style={{ display: "flex", justifyContent: "center" }}>
                <input
                  type="checkbox"
                  checked={p.inName}
                  onChange={() => toggle(p)}
                  aria-label={`Add ${p.part} to the name`}
                  data-testid="part-in-name"
                  style={{ margin: 0, width: 15, height: 15, accentColor: c.amber, cursor: "pointer" }}
                />
              </span>
              <span style={uiText(13, c.heading, { overflowWrap: "anywhere" })}>{p.part}</span>
              <span style={uiText(12, p.make ? c.textPrimary : c.textFaint, { overflowWrap: "anywhere" })}>{p.make || "—"}</span>
              <span style={monoText(12, p.model ? c.textPrimary : c.textFaint, { overflowWrap: "anywhere" })}>{p.model || "—"}</span>
              <span style={uiText(12, p.installedOn ? c.textMuted : c.textFaint)}>{fmtDate(p.installedOn)}</span>
              <span style={uiText(12, p.note ? c.textMuted : c.textFaint, { overflowWrap: "anywhere", lineHeight: 1.5 })}>{p.note || "—"}</span>
              <span style={{ display: "flex", gap: 4, justifyContent: "flex-end" }}>
                <button onClick={() => { setAdding(false); setEditingId(p.id); }} title="Change this part" aria-label={`Change ${p.part}`} style={{ ...headerButton(), padding: "0 7px" }}>
                  <Pencil size={12} />
                </button>
                <TrashButton title={`Remove ${p.part}`} onClick={() => setRemoving(p)} />
              </span>
            </div>
            {leftOut(p) && (
              <div data-testid="part-left-out" style={uiText(11, c.textFaint, { paddingLeft: 64, marginTop: 3 })}>{leftOut(p)}</div>
            )}
          </div>
        ),
      )}
      {adding ? (
        <PartForm
          initial={EMPTY}
          saveLabel="Add part"
          onCancel={() => setAdding(false)}
          onSave={async (fields) => {
            update(await addSubPrinterPart(printer.id, sub.id, fields));
            setAdding(false);
          }}
        />
      ) : (
        <div style={{ paddingTop: 10, borderTop: parts.length ? `1px solid ${c.border}` : "none" }}>
          <button onClick={() => { setEditingId(null); setAdding(true); }} data-testid="part-add" style={headerButton()}>
            <Plus size={12} /> Add part
          </button>
        </div>
      )}
      {tickError && <div style={uiText(12, c.danger, { marginTop: 8 })}>{tickError}</div>}
      <div data-testid="parts-name" style={uiText(12, c.textFaint, { marginTop: 12, lineHeight: 1.6, overflowWrap: "anywhere" })}>
        Name from the ticked parts:{" "}
        {proposed ? (
          <>
            <span style={monoText(12, c.heading)}>{proposed}</span>
            {proposed === sub.name && " (its name now)"}
          </>
        ) : (
          "none yet: tick a part that has a model"
        )}
      </div>
      {removing && (
        <ConfirmDialog
          title="Remove part"
          confirmLabel="Remove"
          onClose={() => setRemoving(null)}
          onConfirm={async () => update(await deleteSubPrinterPart(printer.id, sub.id, removing.id))}
        >
          Remove <b style={{ color: c.heading }}>{removing.part}</b>
          {removing.make || removing.model ? <> ({[removing.make, removing.model].filter(Boolean).join(" ")})</> : null} from {sub.name}’s parts?
        </ConfirmDialog>
      )}
    </fieldset>
  );
}
