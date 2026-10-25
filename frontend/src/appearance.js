// Choosing and applying a look: colour scheme, text brightness, font, text size, 3MF file name colour. Saved per browser.
import { PRESETS, FONTS, SIZES, DEFAULT_APPEARANCE } from "./palettes.js";
import { c, ui, setFontScale } from "./theme.js";

const STORAGE_KEY = "farmhand.appearance";

const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));

// Anything unrecognised (an old or hand-edited value) falls back to the default for that one setting.
export function normalizeAppearance(raw) {
  const a = raw && typeof raw === "object" ? { ...raw } : {};
  if (a.font === "georgia") a.font = "play"; // Georgia was replaced by Play: anyone who had it keeps a sensible choice
  const contrast = Number(a.contrast);
  return {
    scheme: PRESETS.some((p) => p.id === a.scheme) ? a.scheme : DEFAULT_APPEARANCE.scheme,
    contrast: Number.isFinite(contrast) ? clamp(Math.round(contrast), 0, 100) : DEFAULT_APPEARANCE.contrast,
    font: FONTS.some((f) => f.id === a.font) ? a.font : DEFAULT_APPEARANCE.font,
    size: SIZES.some((s) => s.id === a.size) ? a.size : DEFAULT_APPEARANCE.size,
    file_name_color: typeof a.file_name_color === "string" && /^#[0-9a-fA-F]{6}$/.test(a.file_name_color)
      ? a.file_name_color.toUpperCase()
      : DEFAULT_APPEARANCE.file_name_color, // "auto" = the scheme's own blue
  };
}

export function loadAppearance() {
  try {
    return normalizeAppearance(JSON.parse(localStorage.getItem(STORAGE_KEY)));
  } catch {
    return { ...DEFAULT_APPEARANCE }; // nothing saved, or storage unavailable
  }
}

export function saveAppearance(appearance) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(appearance));
  } catch {
    /* storage unavailable: the choice just won't be remembered */
  }
}

// Blend two #RRGGBB colours: t = 0 is `a`, t = 1 is `b`.
export function mixHex(a, b, t) {
  const channel = (hex, i) => parseInt(hex.slice(1 + i * 2, 3 + i * 2), 16);
  const out = [0, 1, 2].map((i) => Math.round(channel(a, i) + (channel(b, i) - channel(a, i)) * t));
  return "#" + out.map((v) => v.toString(16).padStart(2, "0")).join("").toUpperCase();
}

// The scheme's colours, with the three text colours pulled toward the heading colour by the brightness
// setting (toward white on a dark scheme, toward black on the light one).
export function paletteFor(scheme, contrast) {
  const preset = PRESETS.find((p) => p.id === scheme) || PRESETS[0];
  const t = clamp(contrast, 0, 100) / 100;
  const colors = { ...preset.colors };
  for (const key of ["textPrimary", "textMuted", "textFaint"]) colors[key] = mixHex(colors[key], colors.heading, t);
  return { colors, mode: preset.mode };
}

export function applyAppearance(appearance) {
  const a = normalizeAppearance(appearance);
  const { colors, mode } = paletteFor(a.scheme, a.contrast);
  if (a.file_name_color !== "auto") colors.fileName = a.file_name_color; // a colour of their own for 3MF names
  Object.assign(c, colors);
  ui.fontFamily = FONTS.find((f) => f.id === a.font).stack;
  setFontScale(SIZES.find((s) => s.id === a.size).scale);
  if (typeof document !== "undefined") {
    document.documentElement.style.colorScheme = mode; // native controls (scrollbars, checkboxes) follow
    document.documentElement.style.background = c.bg;
    document.body.style.background = c.bg;
    document.body.style.color = c.textPrimary;
  }
}
