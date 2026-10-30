import { useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { c, fs, mono } from "../theme.js";
import { errorText, getSubPrinterParts, saveSubPrinterParts } from "../api.js";
import { fieldBox, headerButton, monoText, primaryButton, uiText } from "../styles.js";

import { TrashButton } from "../components/common/ui.jsx";

// A sub printer's Printer parts page, in its Printer Settings window: the parts fitted to it, written down by hand
// (what it is, who makes it, its model, when it was fitted, a note). Kept in Farmhand, not in the 3MFs. Each part
// can be ticked "Add to name": the ticked parts' models make the name the sub printer can be renamed to when the
// window closes (nameFromParts). Every part can be changed, added or removed on the page, and nothing is kept until
// Save, which saves the whole list at once; closing the window with changes not saved asks whether to save them.

const EMPTY = { part: "", make: "", model: "", installedOn: "", note: "", inName: false };
const COLUMNS = "56px minmax(90px, 1fr) minmax(90px, 1fr) minmax(110px, 1.3fr) 130px minmax(130px, 1.7fr) 30px";

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

// A part as it's edited: its fields as typed, and `key` (its id, or a made-up one for a new part not saved yet)
const editable = (p) => ({ key: p.id, id: p.id, part: p.part, make: p.make, model: p.model, installedOn: p.installedOn || "", note: p.note, inName: p.inName });
const asSaved = (p) => ({ part: p.part.trim(), make: p.make.trim(), model: p.model.trim(), installedOn: p.installedOn || "", note: p.note.trim(), inName: !!p.inName, id: p.id });
const blank = (p) => p.id == null && !p.part.trim() && !p.make.trim() && !p.model.trim() && !p.installedOn && !p.note.trim();
const same = (a, b) => JSON.stringify(a.map(asSaved)) === JSON.stringify(b.map(asSaved));

// The window's hold on a sub printer's parts, loaded once when it opens (so they survive moving between its pages):
// `parts` as saved, `draft` as edited on the page, `unsaved` while they differ, and `changed` once a save went
// through (for the rename question). `save()` saves the draft: it resolves to the list as saved, or null with
// `saveError` set.
export function useSubPrinterParts(printer, sub) {
  const [parts, setParts] = useState(null);
  const [draft, setDraft] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [saveError, setSaveError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [changed, setChanged] = useState(false);
  useEffect(() => {
    let cancelled = false;
    getSubPrinterParts(printer.id, sub.id)
      .then((list) => {
        if (cancelled) return;
        setParts(list);
        setDraft(list.map(editable));
      })
      .catch((e) => !cancelled && setLoadError(errorText(e)));
    return () => {
      cancelled = true;
    };
  }, [printer.id, sub.id]);

  const rows = (draft || []).filter((p) => !blank(p)); // a part added and left empty isn't saved
  const unsaved = !!parts && !same(rows, parts.map(editable));
  const save = async () => {
    const missing = rows.find((p) => !p.part.trim());
    if (missing) {
      setSaveError("Say what each part is (e.g. Hotend): one has a make, model or note but no part");
      return null;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const removes = parts.some((p) => !rows.some((r) => r.id === p.id));
      const list = await saveSubPrinterParts(printer.id, sub.id, rows.map(asSaved), removes);
      setParts(list);
      setDraft(list.map(editable));
      setChanged(true);
      return list;
    } catch (e) {
      setSaveError(errorText(e));
      return null;
    } finally {
      setSaving(false);
    }
  };
  return { parts, draft, setDraft, loadError, saveError, saving, unsaved, changed, save };
}

// Why a ticked part isn't in the name (or null when it is, or isn't ticked)
const leftOut = (p) => {
  if (!p.inName) return null;
  if (!p.model.trim()) return "no model yet, so it isn’t in the name";
  if (isGantry(p) && !saysAwd(p)) return "only in the name when its make or model says AWD, 4WD or quad";
  return null;
};

let nextKey = 0; // for parts added on the page, until they're saved and have an id

// `state` is the window's useSubPrinterParts
export function PrinterParts({ printer, sub, state }) {
  const { parts, draft, setDraft, loadError, saveError, saving, unsaved, save } = state;
  if (loadError) return <div style={uiText(13, c.amber)}>Couldn't load its parts: {loadError}</div>;
  if (!draft) return <div style={uiText(13, c.textFaint)}>Loading parts…</div>;

  const lockedNames = new Set(parts.filter((p) => DEFAULT_PART_NAMES.has(p.part)).map((p) => p.id)); // saved default parts
  const change = (key, name, value) => setDraft((list) => list.map((p) => (p.key === key ? { ...p, [name]: value } : p)));
  const add = () => setDraft((list) => [...list, { ...EMPTY, key: `new-${nextKey++}`, id: null }]);
  const remove = (key) => setDraft((list) => list.filter((p) => p.key !== key));
  const box = { ...fieldBox(), fontSize: fs(12), padding: "4px 8px", minWidth: 0, width: "100%", boxSizing: "border-box" };
  const proposed = nameFromParts(printer.name, draft);

  return (
    <fieldset data-testid="printer-parts" style={{ border: `1px solid ${c.border}`, borderRadius: 4, padding: "6px 14px 12px", margin: 0, minWidth: 0 }}>
      <legend style={uiText(13, c.heading, { fontWeight: 600, padding: "0 6px" })}>Printer parts</legend>
      <div style={uiText(12, c.textFaint, { marginBottom: 10, lineHeight: 1.5 })}>
        The parts fitted to <span style={mono}>{sub.name}</span>. Written down here and kept in Farmhand (and its settings
        copy); the 3MF files don’t carry them. Change any of them, then <b>Save</b>. Tick <b>Add to name</b> to put a
        part’s model in the sub printer’s name: when you close this window after saving its parts, you’re asked whether
        to rename it.
      </div>
      <div style={{ display: "grid", gridTemplateColumns: COLUMNS, gap: 8, padding: "0 0 6px", alignItems: "end" }}>
        {["Add to name", "Part", "Make", "Model", "Installed", "Note", ""].map((h, i) => (
          <span key={i} style={uiText(11, c.textFaint, i === 0 ? { textAlign: "center", lineHeight: 1.2 } : undefined)}>{h}</span>
        ))}
      </div>
      {draft.length === 0 && (
        <div style={uiText(13, c.textFaint, { padding: "10px 0", borderTop: `1px solid ${c.border}` })}>No parts written down yet.</div>
      )}
      {draft.map((p) => {
        const locked = lockedNames.has(p.id);
        const label = p.part.trim() || "the new part";
        return (
          <div key={p.key} data-testid="printer-part" style={{ padding: "6px 0", borderTop: `1px solid ${c.border}` }}>
            <div style={{ display: "grid", gridTemplateColumns: COLUMNS, gap: 8, alignItems: "center" }}>
              <span style={{ display: "flex", justifyContent: "center" }}>
                <input
                  type="checkbox"
                  checked={!!p.inName}
                  onChange={(e) => change(p.key, "inName", e.target.checked)}
                  aria-label={`Add ${label} to the name`}
                  data-testid="part-in-name"
                  disabled={saving}
                  style={{ margin: 0, width: 15, height: 15, accentColor: c.amber, cursor: "pointer" }}
                />
              </span>
              {locked ? (
                <span data-testid="part-part-locked" title="One of the default parts: its name can't be changed" style={uiText(13, c.heading, { overflowWrap: "anywhere" })}>
                  {p.part}
                </span>
              ) : (
                <input autoFocus={p.id == null} value={p.part} onChange={(e) => change(p.key, "part", e.target.value)} placeholder="Part (e.g. Hotend)" aria-label="Part" data-testid="part-part" style={box} disabled={saving} />
              )}
              <input value={p.make} onChange={(e) => change(p.key, "make", e.target.value)} placeholder="Make" aria-label={`${label}: make`} data-testid="part-make" style={box} disabled={saving} />
              <input value={p.model} onChange={(e) => change(p.key, "model", e.target.value)} placeholder="Model" aria-label={`${label}: model`} data-testid="part-model" style={{ ...box, ...mono }} disabled={saving} />
              <input type="date" value={p.installedOn || ""} onChange={(e) => change(p.key, "installedOn", e.target.value)} aria-label={`${label}: installed on`} data-testid="part-installed" style={box} disabled={saving} />
              <input value={p.note} onChange={(e) => change(p.key, "note", e.target.value)} placeholder="Note" aria-label={`${label}: note`} data-testid="part-note" style={box} disabled={saving} />
              <span style={{ display: "flex", justifyContent: "flex-end" }}>
                <TrashButton title={`Remove ${label} (when you save)`} onClick={() => remove(p.key)} />
              </span>
            </div>
            {leftOut(p) && (
              <div data-testid="part-left-out" style={uiText(11, c.textFaint, { paddingLeft: 64, marginTop: 3 })}>{leftOut(p)}</div>
            )}
          </div>
        );
      })}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", paddingTop: 10, borderTop: draft.length ? `1px solid ${c.border}` : "none" }}>
        <button onClick={add} disabled={saving} data-testid="part-add" style={headerButton()}>
          <Plus size={12} /> Add part
        </button>
        <button onClick={save} disabled={saving || !unsaved} data-testid="parts-save" style={{ ...primaryButton(saving || !unsaved), fontSize: fs(12), padding: "5px 14px" }}>
          {saving ? "Saving…" : "Save"}
        </button>
        <span data-testid="parts-status" style={uiText(12, unsaved ? c.amber : c.textFaint)}>
          {unsaved ? "Changes not saved yet" : "Saved"}
        </span>
      </div>
      {saveError && <div data-testid="parts-save-error" style={uiText(12, c.danger, { marginTop: 8, lineHeight: 1.5 })}>{saveError}</div>}
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
    </fieldset>
  );
}
