import { createContext, useContext, useState } from "react";
import { ChevronDown } from "lucide-react";
import { SLICER_SCHEMES } from "../palettes.js";
import { c, fs, look, mono, ui } from "../theme.js";
import { uiText } from "../styles.js";
import { hasValue, shownRows, unescape } from "./pages.js";

// A slicer's settings pages, drawn the way the slicer draws them but never editable: tick boxes, drop-downs, colour
// swatches, G-code boxes, each with its label and unit. The layouts themselves (which pages, which groups, which
// settings) are in boss.js and orca.js, built from the parts in pages.js, which says what a page looks like.
//
// Kinds: "bool" (a tick box), "enum" (a drop-down), "color", "gcode" (a text box across the page), "bed". Anything
// else is the unit shown after the field. A row whose setting isn't in the file is left out (each slicer version
// has its own), and so is a group or page left with nothing in it.
//
// They're drawn in the colours of the slicer whose layout they follow (SLICER_SCHEMES in palettes.js): put them
// inside <SlicerColors.Provider value={slicerColors("prusa")}>. Outside one they take Farmhand's own colours.

export const SlicerColors = createContext(null);
// In a comparison: the settings that differ between the two files, and which side this is ("left" | "right"), so
// those rows are marked in that side's colour (Farmhand's: the accent left, the secondary right)
export const DiffMarks = createContext(null);
// A slicer's colours, dark or light to match the scheme in use
export const slicerColors = (slicer) => SLICER_SCHEMES[slicer][look.mode === "light" ? "light" : "dark"];
const appColors = () => ({
  bg: c.panel, field: c.panelAlt, border: c.border, borderStrong: c.borderStrong, heading: c.heading, textPrimary: c.textPrimary,
  textMuted: c.textMuted, textFaint: c.textFaint, accent: c.amber, accentText: c.amber, accentDim: c.amberDim,
});
export const useSlicerColors = () => useContext(SlicerColors) || appColors();

const KINDS = ["bool", "enum", "color", "gcode", "bed"];
// The label column and the value column, the same in every group so the fields line up down a page
const COLUMNS = "minmax(110px, 260px) minmax(0, 1fr)";

const isOn = (v) => v === "1" || v === 1 || v === true || v === "true";
const bedSummary = (raw) => {
  const pts = String(raw || "").split(",").map((p) => p.split("x").map(Number)).filter((p) => p.length === 2 && p.every(Number.isFinite));
  if (pts.length < 3) return raw || "";
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const w = Math.max(...xs) - Math.min(...xs), h = Math.max(...ys) - Math.min(...ys);
  return pts.length === 4 ? `Rectangular, ${w} × ${h} mm, origin ${-Math.min(...xs)}, ${-Math.min(...ys)}` : `Custom shape, ${pts.length} points, ${w} × ${h} mm`;
};

// The box a value sits in, in `p`'s colours (a slicer's, or Farmhand's own)
export const boxStyle = (extra, p = appColors()) => ({
  ...mono, fontSize: fs(12), color: p.textPrimary, background: p.field, border: `1px solid ${p.border}`, borderRadius: 3,
  padding: "3px 8px", minHeight: 24, boxSizing: "border-box", display: "inline-flex", alignItems: "center", gap: 6, ...extra,
});

function Field({ kind, value, choices }) {
  const p = useSlicerColors();
  const box = (extra) => boxStyle(extra, p);
  if (kind === "bool") {
    return <input type="checkbox" checked={isOn(value)} readOnly disabled aria-label={isOn(value) ? "on" : "off"} style={{ margin: 0, width: 15, height: 15, accentColor: p.accent }} />;
  }
  if (value == null || value === "") return <span style={box({ minWidth: 90 })}><span style={{ color: p.textFaint }}>—</span></span>;
  if (kind === "enum") {
    return (
      <span style={box({ minWidth: 170, justifyContent: "space-between" })}>
        {choices?.[value] || value}
        <ChevronDown size={12} color={p.textFaint} />
      </span>
    );
  }
  if (kind === "color") {
    return (
      <span style={box()}>
        {String(value).split(/[;,]/).map((v, i) => (
          <span key={i} style={{ width: 28, height: 14, borderRadius: 2, background: v.replace(/"/g, ""), border: `1px solid ${p.borderStrong}` }} />
        ))}
        {value}
      </span>
    );
  }
  if (kind === "bed") return <span style={box({ fontFamily: "inherit", ...ui })}>{bedSummary(value)}</span>;
  return <span style={box({ minWidth: 90, maxWidth: "100%", overflowWrap: "anywhere" })}>{unescape(value)}</span>;
}

function Row(props) {
  const marks = useContext(DiffMarks);
  if (!marks?.keys.has(props.settingKey)) return <PlainRow {...props} />;
  const color = marks.side === "right" ? c.teal : c.amber;
  return (
    <div data-testid="diff-field" data-side={marks.side} style={{ borderLeft: `3px solid ${color}`, background: `${color}1F`, borderRadius: 2, paddingLeft: 4 }}>
      <PlainRow {...props} />
    </div>
  );
}

function PlainRow({ label, kind, unit, value, limits, choices }) {
  const p = useSlicerColors();
  if (kind === "gcode") {
    const text = value == null ? "" : unescape(value);
    return (
      <div>
        {label && <div style={uiText(12, p.textMuted, { margin: "4px 0" })}>{label}:</div>}
        <textarea
          readOnly
          value={text}
          rows={Math.min(14, Math.max(3, text.split("\n").length))}
          aria-label={label || "G-code"}
          style={{ ...boxStyle({ display: "block", width: "100%", resize: "vertical", whiteSpace: "pre", overflowX: "auto", lineHeight: 1.5, padding: "6px 8px" }, p) }}
        />
      </div>
    );
  }
  const values = limits && value != null ? String(value).split(",") : [value];
  // a speed or width given as a percentage ("50%") is of something else, so the unit doesn't apply
  const showUnit = unit && !values.every((v) => String(v ?? "").trim().endsWith("%"));
  return (
    <div style={{ display: "grid", gridTemplateColumns: COLUMNS, gap: 12, alignItems: "center", padding: "3px 0" }}>
      <div style={uiText(12, p.textMuted, { textAlign: "right" })}>{label}:</div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", minWidth: 0 }}>
        {values.map((v, i) => <Field key={i} kind={kind} value={v} choices={choices} />)}
        {showUnit && <span style={uiText(12, p.textFaint)}>{unit}</span>}
      </div>
    </div>
  );
}

function Group({ group, rows, value, choices }) {
  const p = useSlicerColors();
  return (
    <fieldset style={{ border: `1px solid ${p.border}`, borderRadius: 4, padding: "6px 14px 10px", margin: 0, minWidth: 0 }}>
      <legend style={uiText(13, p.heading, { fontWeight: 600, padding: "0 6px" })}>{group.title}</legend>
      {group.limits && (
        <div style={{ display: "grid", gridTemplateColumns: COLUMNS, gap: 12 }}>
          <span />
          <span style={uiText(11, p.textFaint, { display: "flex", gap: 8 })}>
            <span style={{ minWidth: 90 }}>Normal</span>
            <span>Stealth</span>
          </span>
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {rows.map(([key, label, kindOrUnit]) => {
          const kind = KINDS.includes(kindOrUnit) ? kindOrUnit : null;
          return <Row key={key} settingKey={key} label={label} kind={kind} unit={kind ? null : kindOrUnit} value={value(key)} limits={group.limits} choices={choices[key]} />;
        })}
      </div>
    </fieldset>
  );
}

// A set of pages with their list down the left (PrusaSlicer) or across the top (OrcaSlicer). `value(key, page)` reads
// a setting for a page (an Extruder page reads its own extruder's value). `choices`: how the slicer names drop-down
// choices, by key. `has(key, page)` picks the rows to show (by default, the ones the file has a value for). In a
// comparison the page is chosen from outside (`pageId`, `onPage`) so both sides turn together, `diffsOn(page)`
// counts the differences on a page for its button, and `scroll` = { ref, onScroll } lets the two sides scroll together.
export function SettingsPages({ pages, value, choices = {}, nav = "left", label, pageId: shownId, onPage, has, diffsOn, scroll }) {
  const col = useSlicerColors();
  const [ownId, setOwnId] = useState(pages[0]?.id);
  const pageId = shownId !== undefined ? shownId : ownId;
  const setPageId = onPage || setOwnId;
  const page = pages.find((p) => p.id === pageId) || pages[0];
  if (!page) return <div style={uiText(13, col.textFaint)}>Nothing on these pages in this file.</div>;
  const read = (key) => value(key, page);
  const show = has || hasValue(value);
  const left = nav === "left";

  return (
    <div style={{ display: "flex", flexDirection: left ? "row" : "column", gap: 14, minHeight: 420 }}>
      <nav
        aria-label={label}
        style={{
          display: "flex", flexDirection: left ? "column" : "row", flexWrap: left ? "nowrap" : "wrap", gap: 2,
          ...(left
            ? { width: 170, flexShrink: 0, borderRight: `1px solid ${col.border}`, paddingRight: 10 }
            : { borderBottom: `1px solid ${col.border}`, paddingBottom: 6 }),
        }}
      >
        {pages.map((p) => {
          const on = p.id === page.id;
          return (
            <button
              key={p.id}
              data-testid="preset-page"
              aria-current={on ? "page" : undefined}
              onClick={() => setPageId(p.id)}
              style={{
                ...ui, fontSize: fs(13), display: "flex", alignItems: "center", gap: 8, textAlign: "left", padding: "6px 8px",
                borderRadius: 3, border: "none", cursor: "pointer", background: on ? col.accentDim : "transparent",
                color: on ? col.accentText : col.textMuted, fontWeight: on ? 600 : 400,
                ...(!left && { background: "transparent", borderBottom: `2px solid ${on ? col.accent : "transparent"}`, borderRadius: 0 }),
              }}
            >
              <p.Icon size={14} color={on ? col.accentText : col.textFaint} />
              {p.title}
              {diffsOn?.(p) > 0 && (
                <span data-testid="page-diffs" title="Settings that differ on this page" style={uiText(11, col.textMuted, { marginLeft: "auto", paddingLeft: 6, fontWeight: 600 })}>
                  {diffsOn(p)}
                </span>
              )}
            </button>
          );
        })}
      </nav>
      <div data-testid="preset-page-body" ref={scroll?.ref} onScroll={scroll?.onScroll} style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 12, maxHeight: "62vh", overflowY: "auto", paddingRight: 4 }}>
        {page.render
          ? page.render()
          : page.groups.map((g) => {
              const rows = shownRows(g, show, page);
              return rows.length ? <Group key={g.title} group={g} rows={rows} value={read} choices={choices} /> : null;
            })}
      </div>
    </div>
  );
}
