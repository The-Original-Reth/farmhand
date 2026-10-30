// The live theme. Components read these at render time (`c.amber`, `...ui`, `fs(13)`), and the Appearance panel
// changes them IN PLACE (appearance.js), so a new look applies to everything already on screen without
// remounting anything: the page you're on, open dialogs and your selections are all left alone.
import { PRESETS, FONTS, DEFAULT_APPEARANCE } from "./palettes.js";

export const c = { ...PRESETS.find((p) => p.id === DEFAULT_APPEARANCE.scheme).colors };
// Whether the scheme in use is dark or light (a slicer's settings window takes its dark or light colours from it)
export const look = { mode: PRESETS.find((p) => p.id === DEFAULT_APPEARANCE.scheme).mode };

export const ui = { fontFamily: FONTS.find((f) => f.id === DEFAULT_APPEARANCE.font).stack };
export const mono = { fontFamily: "'JetBrains Mono', ui-monospace, monospace" };

// Text size: every font size in the app goes through fs(), which applies the chosen size.
let fontScale = 1;
export const fs = (px) => Math.round(px * fontScale * 10) / 10;
export const setFontScale = (scale) => {
  fontScale = scale;
};
