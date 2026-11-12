import { c } from "../theme.js";
import { headerButton, uiText } from "../styles.js";
import { box, colourBox, label12 } from "./streamStyles.js";
import { fontFamily } from "./shapes.js";

// The Stream page's small choosers, alike wherever they're used (the square editor, Defaults, the holding screen).

// The name of the font with this key, as the fonts list has it (Play when there's none)
export const fontLabel = (fonts, key) => fonts.find((f) => f.key === (key || "play"))?.label || "Play";

// A font list, each written in its own font. `value`: the chosen font's key. With `defaultLabel`, its first choice ("",
// null to `onPick`) is `fallback`'s font under that label (a square's "Default (Play)", the holding screen's "The
// stream's"); without it every choice is a font.
export function FontPick({ testid, value, onPick, fonts, fallback, defaultLabel, style }) {
  return (
    <select
      data-testid={testid} value={value || ""} onChange={(e) => onPick(e.target.value || null)}
      style={{ ...box(), ...style, fontFamily: fontFamily(value || fallback) }}
    >
      {defaultLabel && <option value="">{defaultLabel}</option>}
      {fonts.map((f) => <option key={f.key} value={f.key} style={{ fontFamily: fontFamily(f.key) }}>{f.label}</option>)}
    </select>
  );
}

// A colour picker with its label (`children`). `value`: "#RRGGBB", or null while it's `fallback`'s. `reset`: { label,
// to (null: back to the fallback), title }: a button back to `to`, shown while it's another colour; `idle`: words shown
// instead while it isn't. `labelStyle` and `swatch`: a panel's larger look (the square editor's by default).
export function ColourPick({ testid, value, onPick, fallback, reset, idle, children, labelStyle = label12, swatch = colourBox }) {
  const to = reset?.to ?? null;
  const away = !!reset && (value || null) !== to;
  return (
    <label style={labelStyle}>
      <input type="color" data-testid={testid} value={(value || fallback).toLowerCase()} onChange={(e) => onPick(e.target.value.toUpperCase())} style={swatch} />
      {children}
      {away ? (
        <button type="button" onClick={() => onPick(to)} style={headerButton()} title={reset.title}>
          {reset.label}
        </button>
      ) : (
        idle && <span style={uiText(11, c.textFaint)}>{idle}</span>
      )}
    </label>
  );
}

// a panel's colour swatch and label row (Defaults, the holding screen), a little larger than the square editor's
export const panelSwatch = { width: 34, height: 24, padding: 0, border: `1px solid ${c.border}`, background: "none", cursor: "pointer" };
export const panelRow = uiText(13, c.textPrimary, { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" });
