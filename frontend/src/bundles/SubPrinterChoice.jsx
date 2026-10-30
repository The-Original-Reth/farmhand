import { useState } from "react";
import { c, fs, mono, ui } from "../theme.js";
import { fieldBox, uiText } from "../styles.js";

// Which sub printer (printer preset) a 3MF being uploaded goes to. The printer's default sub printer (starred on the
// printer page), if it has one. Else Farmhand guesses from the preset the file was sliced with: a sub printer known by
// that name (it was renamed from it, or given 3MFs with it by hand), else the one called that, else a new one named
// after it. Either can be changed to another of the printer's sub printers, or to a new one with any name.
//   pick: { kind: "existing", id } | { kind: "new", name } | { kind: "none" }

function guessSubPrinter(printer, presetName) {
  const subs = printer?.subPrinters || [];
  const def = subs.find((s) => s.id === printer?.defaultSubPrinterId);
  if (def) return { kind: "existing", id: def.id };
  if (presetName) {
    const known = subs.find((s) => (s.aliases || []).includes(presetName)) || subs.find((s) => s.name === presetName);
    return known ? { kind: "existing", id: known.id } : { kind: "new", name: presetName };
  }
  return { kind: "none" };
}

// What to send with the upload (api.js createBundle / addBundleVersion: subPrinter)
export const subPrinterFields = (pick) =>
  pick.kind === "existing" ? { subPrinterId: pick.id } : pick.kind === "new" ? { newSubPrinterName: pick.name.trim() } : {};

// The guess, until it's changed here. Starts over (back to the guess) whenever `resetKey` changes: a different file
// or printer.
export function useSubPrinterPick(printer, presetName, resetKey) {
  const [chosen, setChosen] = useState({ key: resetKey, pick: null });
  const guess = guessSubPrinter(printer, presetName);
  const pick = chosen.key === resetKey && chosen.pick ? chosen.pick : guess;
  return { pick, guess, setPick: (next) => setChosen({ key: resetKey, pick: next }) };
}

export function SubPrinterChoice({ printer, presetName, pick, guess, onChange }) {
  const subs = printer?.subPrinters || [];
  const value = pick.kind === "existing" ? String(pick.id) : pick.kind;
  const guessed = guess.kind === pick.kind && (guess.kind !== "existing" || guess.id === pick.id);
  const box = { ...fieldBox(), padding: "7px 10px", width: "100%", boxSizing: "border-box" };

  let why = null;
  const isDefault = pick.kind === "existing" && pick.id === printer?.defaultSubPrinterId;
  if (guessed && isDefault) {
    why = <>{printer.name}’s default sub printer{presetName && <>; the file was sliced with <span style={mono}>{presetName}</span></>}.</>;
  } else if (guessed && presetName) {
    const sub = subs.find((s) => s.id === pick.id);
    why =
      pick.kind === "new" ? (
        <>Sliced with <span style={mono}>{presetName}</span>, which {printer?.name || "this printer"} doesn’t have yet.</>
      ) : sub && sub.name !== presetName ? (
        <>Sliced with <span style={mono}>{presetName}</span>, whose 3MFs go to this sub printer.</>
      ) : (
        <>Sliced with this preset.</>
      );
  } else if (!presetName) {
    why = <>This file doesn’t say which printer preset it was sliced with.</>;
  }

  return (
    <div data-testid="sub-printer-choice" style={{ border: `1px solid ${c.border}`, borderRadius: 4, padding: 12, marginBottom: 14, background: c.panelAlt }}>
      <div style={uiText(12, c.textFaint, { marginBottom: 6 })}>
        Sub printer{guessed && (isDefault ? " (the default)" : " (Farmhand’s guess)")}
      </div>
      <select
        data-testid="sub-printer-pick"
        value={value}
        onChange={(e) => {
          const v = e.target.value;
          if (v === "new") onChange({ kind: "new", name: presetName || "" });
          else if (v === "none") onChange({ kind: "none" });
          else onChange({ kind: "existing", id: Number(v) });
        }}
        style={{ ...box, ...ui, fontSize: fs(13) }}
      >
        {subs.map((s) => (
          <option key={s.id} value={String(s.id)}>{s.name}{s.id === printer?.defaultSubPrinterId ? " (default)" : ""}</option>
        ))}
        <option value="new">Create a new sub printer…</option>
        {!presetName && <option value="none">None</option>}
      </select>
      {pick.kind === "new" && (
        <input
          data-testid="sub-printer-new-name"
          value={pick.name}
          onChange={(e) => onChange({ kind: "new", name: e.target.value })}
          placeholder="Name of the new sub printer"
          aria-label="Name of the new sub printer"
          style={{ ...box, ...mono, fontSize: fs(12), marginTop: 8 }}
        />
      )}
      {why && <div style={uiText(11, c.textFaint, { marginTop: 6, lineHeight: 1.5 })}>{why}</div>}
      {presetName && pick.kind !== "none" && !guessed && (
        <div style={uiText(11, c.textFaint, { marginTop: 6, lineHeight: 1.5 })}>
          Farmhand will remember this: the next 3MF sliced with <span style={mono}>{presetName}</span> is guessed to go
          here too.
        </div>
      )}
    </div>
  );
}
