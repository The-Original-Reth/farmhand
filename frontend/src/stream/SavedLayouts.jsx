import { useState } from "react";
import { c } from "../theme.js";
import { cancelButton, fieldBox, headerButton, panelBox, primaryButton, uiText } from "../styles.js";

// The Stream page's saved layouts, kept in Farmhand's settings (and so in the settings copy's streams folder, and brought
// back by Load all). A layout is the grid (its size and what's in each square), the whole grid or taking turns, the
// timings, the words and the border's colour; not the key, title or description. The page's Save saves
// one (SaveChoice: a new one, or over one there is); this panel switches the stream to one, or deletes it.

const help = uiText(12, c.textFaint, { lineHeight: 1.5 });

// A layout as the settings keep it, from the page's choices
export const layoutOf = (name, shown) => ({
  name, cols: shown.cols, rows: shown.rows, cells: shown.cells, layout: shown.layout, seconds_all: Number(shown.secondsAll) || 0,
  seconds_each: Number(shown.secondsEach) || 0, show_status: !!shown.showStatus, border_color: shown.borderColor, background: shown.background, font: shown.font, color: shown.color,
});
// Whether the page shows this layout now (timings only count when taking turns)
export const sameAs = (saved, shown) => {
  const now = layoutOf(saved.name, shown);
  return saved.cols === now.cols && saved.rows === now.rows && JSON.stringify(saved.cells) === JSON.stringify(now.cells)
    && saved.layout === now.layout && saved.show_status === now.show_status && saved.border_color === now.border_color
    && (saved.background || "#000000") === (now.background || "#000000")
    && (saved.font || "play") === (now.font || "play") && (saved.color || "#FFFFFF") === (now.color || "#FFFFFF")
    && (saved.layout === "grid" || (saved.seconds_all === now.seconds_all && saved.seconds_each === now.seconds_each));
};
const camerasOf = (l) => l.cells.filter((x) => x?.camera).map((x) => x.camera);
// A saved layout as the page's choices (the part of them a layout holds)
export const shownOf = (l) => ({
  cols: l.cols, rows: l.rows, cells: l.cells, layout: l.layout, secondsAll: l.seconds_all, secondsEach: l.seconds_each,
  showStatus: l.show_status, borderColor: l.border_color, background: l.background || "#000000", font: l.font || "play", color: l.color || "#FFFFFF",
});
const summaryOf = (l) => {
  const n = camerasOf(l).length;
  const count = (test, one) => {
    const k = l.cells.filter(test).length;
    return k ? ` · ${k} ${one}${k === 1 ? "" : "s"}` : "";
  };
  return `${l.cols}×${l.rows} · ${n} camera${n === 1 ? "" : "s"}${count((x) => x?.image, "picture")}${count((x) => x?.slideshow, "slideshow")}${count((x) => x && !x.camera && x.text?.trim(), "text")} · ${
    l.layout === "cycle" ? `taking turns (${l.seconds_all ? `grid ${l.seconds_all} s, ` : ""}each ${l.seconds_each} s)` : "whole grid"
  }${l.show_status ? "" : " · no words"}`;
};

// The saved layouts: Switch to one (the stream takes it straight away, without asking anything; while live it starts
// again with it), or Delete one. The one the stream is using is marked, and two saved the same are pointed out.
// `layouts`: as the settings hold them; `onSave(list)`: saves the whole list, resolving once the server has it;
// `saved`: the stream's saved settings; `switchTo(layout)`: makes it the stream's, resolving true once saved;
// `label(key)`: a camera's name.
export function SavedLayoutsPanel({ layouts, onSave, saved, switchTo, label }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [said, setSaid] = useState(null);
  const [removing, setRemoving] = useState(null); // the name of the layout asking "Delete?"

  const remove = async (name) => {
    setBusy(true);
    setError(null);
    try {
      await onSave(layouts.filter((x) => x.name !== name));
      setSaid(`Deleted “${name}”.`);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setBusy(false);
      setRemoving(null);
    }
  };

  return (
    <div data-testid="stream-saved-layouts" style={panelBox({ padding: 16, display: "flex", flexDirection: "column", gap: 12 })}>
      <div style={uiText(14, c.heading, { fontWeight: 600 })}>Saved layouts</div>
      {layouts.length === 0 ? (
        <div style={help}>None yet. Set up the grid, then press Save at the foot of the page to keep it as a layout by name.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {layouts.map((l) => {
            const current = sameAs(l, saved);
            const twin = layouts.find((x) => x.name !== l.name && sameAs(x, { ...saved, ...shownOf(l) }));
            return (
              <div
                key={l.name} data-testid="stream-saved-layout"
                style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 8px", border: `1px solid ${current ? c.amber : c.border}`, borderRadius: 4, flexWrap: "wrap" }}
              >
                <div style={{ flex: 1, minWidth: 160 }}>
                  <div style={uiText(13, c.textPrimary, { fontWeight: 600 })}>
                    {l.name} {current && <span style={uiText(11, c.amber, { fontWeight: 400 })}>· in use</span>}
                  </div>
                  <div style={uiText(11, c.textFaint)} title={camerasOf(l).map(label).join(", ")}>
                    {summaryOf(l)}
                  </div>
                  {twin && (
                    <div style={uiText(11, c.amber)}>The same as “{twin.name}”: switching between them changes nothing.</div>
                  )}
                </div>
                {removing === l.name ? (
                  <>
                    <span style={uiText(12, c.textMuted)}>Delete?</span>
                    <button type="button" disabled={busy} onClick={() => remove(l.name)} style={{ ...headerButton(), color: c.danger, borderColor: c.danger }}>
                      Delete
                    </button>
                    <button type="button" onClick={() => setRemoving(null)} style={headerButton()}>
                      Keep
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button" data-testid="stream-use-layout" disabled={busy || current} title={current ? "The stream is using this layout" : undefined}
                      style={{ ...headerButton(), opacity: current ? 0.45 : 1 }}
                      onClick={async () => {
                        setBusy(true);
                        setError(null);
                        setSaid(null);
                        if (await switchTo(l)) setSaid(`Switched to “${l.name}”.`);
                        setBusy(false);
                      }}
                    >
                      Switch to
                    </button>
                    <button type="button" onClick={() => setRemoving(l.name)} disabled={busy} style={headerButton()}>
                      Delete
                    </button>
                  </>
                )}
              </div>
            );
          })}
        </div>
      )}
      {error ? <div style={uiText(12, c.danger, { lineHeight: 1.5 })}>{error}</div> : said && <div style={uiText(12, c.green)}>{said}</div>}
      <div style={help}>Kept in Farmhand's settings, and as a file each in the settings folder's streams folder; Load all brings them back.</div>
    </div>
  );
}

// What Save asks: keep the page's layout over one of the saved ones (`suggested` to start with: the one last used or
// saved), or as a new one by name. onConfirm({ name, list }) saves the stream and the layouts list; it resolves to true
// once both are saved. Starts on "over one" when there are any.
export function SaveChoice({ layouts, shown, suggested, onConfirm, onCancel, busy }) {
  const [mode, setMode] = useState(layouts.length ? "overwrite" : "new");
  const [target, setTarget] = useState(layouts.some((l) => l.name === suggested) ? suggested : layouts[0]?.name || "");
  const [name, setName] = useState("");
  const [error, setError] = useState(null);
  const confirm = () => {
    if (mode === "overwrite") {
      return onConfirm({ name: target, list: layouts.map((x) => (x.name === target ? layoutOf(target, shown) : x)) });
    }
    const n = name.trim();
    if (!n) return setError("Give the new layout a name.");
    if (n.length > 60) return setError("Keep the name to 60 characters.");
    if (layouts.some((l) => l.name.toLowerCase() === n.toLowerCase())) return setError(`There's already a layout called “${n}”: choose it under Overwrite, or pick another name.`);
    return onConfirm({ name: n, list: [...layouts, layoutOf(n, shown)] });
  };
  return (
    <div data-testid="stream-save-choice" style={panelBox({ padding: 14, display: "flex", flexDirection: "column", gap: 10, borderColor: c.amber })}>
      <div style={uiText(13, c.heading, { fontWeight: 600 })}>Save the layout as</div>
      {layouts.length > 0 && (
        <label style={uiText(13, c.textPrimary, { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" })}>
          <input data-testid="stream-save-overwrite" type="radio" name="stream-save-mode" checked={mode === "overwrite"} onChange={() => setMode("overwrite")} />
          Overwrite
          <select
            data-testid="stream-save-target" value={target} onChange={(e) => (setTarget(e.target.value), setMode("overwrite"))}
            style={{ ...fieldBox(), padding: "4px 6px" }}
          >
            {layouts.map((l) => <option key={l.name} value={l.name}>{l.name}</option>)}
          </select>
        </label>
      )}
      <label style={uiText(13, c.textPrimary, { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" })}>
        <input data-testid="stream-save-new" type="radio" name="stream-save-mode" checked={mode === "new"} onChange={() => setMode("new")} />
        A new layout called
        <input
          data-testid="stream-save-name" value={name} maxLength={60} placeholder="e.g. Whole farm"
          onFocus={() => setMode("new")} onChange={(e) => (setName(e.target.value), setError(null))} onKeyDown={(e) => e.key === "Enter" && confirm()}
          style={{ ...fieldBox(), padding: "4px 8px", flex: 1, minWidth: 140 }}
        />
      </label>
      {error && <div style={uiText(12, c.danger, { lineHeight: 1.5 })}>{error}</div>}
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <button type="button" onClick={onCancel} disabled={busy} style={cancelButton(busy)}>
          Cancel
        </button>
        <button type="button" data-testid="stream-save-confirm" onClick={confirm} disabled={busy} style={primaryButton(busy)}>
          {busy ? "Saving…" : "Save"}
        </button>
      </div>
    </div>
  );
}
