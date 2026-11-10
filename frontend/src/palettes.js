// Colour schemes. Pure data: appearance.js applies one of these to the live theme (theme.js).
//
// Every colour is a 6-digit hex, because some styles append an alpha (`${c.amber}14`).
// "amber" and "teal" are really ROLES, not hues: amber is the accent (buttons, selection, the left side of
// a comparison) and teal is the secondary (the right side of a comparison). A scheme may colour them anything,
// as long as the two stay clearly different from each other.
//
// Text tokens, brightest to quietest: heading, textPrimary, textMuted, textFaint.
// `onAccent` / `onTeal` / `onDanger` are the text colours that sit ON a button filled with that colour.

export const PRESETS = [
  {
    id: "farmhand",
    name: "Farmhand",
    note: "Brighter, whiter text (default)",
    mode: "dark",
    colors: {
      bg: "#1B1D1E", panel: "#232527", panelAlt: "#2A2C2E", panelHover: "#303335",
      border: "#3D4042", borderStrong: "#565A5D",
      textPrimary: "#F4F5F4", textMuted: "#CBCED0", textFaint: "#A3A7AA", heading: "#FFFFFF",
      amber: "#E39F3A", amberDim: "#4A3A20", amberBorder: "#6B5428",
      teal: "#69A0A6", tealDim: "#1F2E30", tealBorder: "#2C4548",
      fileName: "#6AAEF5", // file names (e.g. 3MF files)
      projectOnly: "#B394FF", // the boxed "Project only" tag: an STL or 3MF a project keeps for itself
      green: "#6FBE7A", greenDim: "#233A26", greenBorder: "#345F3C",
      danger: "#E27A72", dangerDim: "#3A2321",
      onAccent: "#241A08", onTeal: "#0B2224", onDanger: "#1B0A09",
    },
  },
  {
    id: "classic",
    name: "Classic grey",
    note: "The original, softer greys",
    mode: "dark",
    classic: true, // the original look, kept as it was: exempt from the legibility check
    colors: {
      bg: "#1B1D1E", panel: "#232527", panelAlt: "#292B2D", panelHover: "#2E3032",
      border: "#37393B", borderStrong: "#484B4D",
      textPrimary: "#ECEDEC", textMuted: "#989C9E", textFaint: "#6C6F71", heading: "#FFFFFF",
      amber: "#E39F3A", amberDim: "#4A3A20", amberBorder: "#5A4626",
      teal: "#69A0A6", tealDim: "#233335", tealBorder: "#2C4548",
      fileName: "#6AAEF5", // file names (e.g. 3MF files)
      projectOnly: "#B394FF", // the boxed "Project only" tag: an STL or 3MF a project keeps for itself
      green: "#6FBE7A", greenDim: "#233A26", greenBorder: "#345F3C",
      danger: "#D9675F", dangerDim: "#3A2321",
      onAccent: "#241A08", onTeal: "#0B2224", onDanger: "#1B0A09",
    },
  },
  {
    id: "contrast",
    name: "High contrast",
    note: "Pure white on black",
    mode: "dark",
    colors: {
      bg: "#000000", panel: "#0B0B0B", panelAlt: "#151515", panelHover: "#1E1E1E",
      border: "#4A4A4A", borderStrong: "#8A8A8A",
      textPrimary: "#FFFFFF", textMuted: "#EFEFEF", textFaint: "#D2D2D2", heading: "#FFFFFF",
      amber: "#FFB000", amberDim: "#4D3600", amberBorder: "#9A6B00",
      teal: "#4FD1DC", tealDim: "#0F3A3E", tealBorder: "#1F7F87",
      fileName: "#5CB8FF", // file names (e.g. 3MF files)
      projectOnly: "#C4A6FF", // the boxed "Project only" tag: an STL or 3MF a project keeps for itself
      green: "#5CE17A", greenDim: "#11381A", greenBorder: "#2A8F45",
      danger: "#FF7A70", dangerDim: "#47110D",
      onAccent: "#1A1000", onTeal: "#021A1C", onDanger: "#220503",
    },
  },
  {
    id: "midnight",
    name: "Midnight blue",
    note: "Blue accent, warm secondary",
    mode: "dark",
    colors: {
      bg: "#0F1624", panel: "#151E30", panelAlt: "#1B2640", panelHover: "#22304F",
      border: "#2B3A5C", borderStrong: "#42578A",
      textPrimary: "#F2F5FB", textMuted: "#C8D2E6", textFaint: "#9DABC8", heading: "#FFFFFF",
      amber: "#6AB0FF", amberDim: "#1F3A5F", amberBorder: "#2F5A92",
      teal: "#FFB86B", tealDim: "#4A3216", tealBorder: "#7A5424",
      fileName: "#8CC8FF", // file names (e.g. 3MF files)
      projectOnly: "#C5A8FF", // the boxed "Project only" tag: an STL or 3MF a project keeps for itself
      green: "#6FD98F", greenDim: "#1A3B28", greenBorder: "#2E6B47",
      danger: "#FF8A80", dangerDim: "#3E1B1B",
      onAccent: "#06182E", onTeal: "#2A1600", onDanger: "#2B0A07",
    },
  },
  {
    id: "violet",
    name: "Violet",
    note: "Purple accent, mint secondary",
    mode: "dark",
    colors: {
      bg: "#16131F", panel: "#1D1A29", panelAlt: "#252136", panelHover: "#2D2942",
      border: "#383352", borderStrong: "#50496F",
      textPrimary: "#F5F3FA", textMuted: "#CFC9E0", textFaint: "#A8A1C0", heading: "#FFFFFF",
      amber: "#B99BFF", amberDim: "#3A2D63", amberBorder: "#5A47A0",
      teal: "#5FD3C8", tealDim: "#12393A", tealBorder: "#1F6A66",
      fileName: "#7FB2FF", // file names (e.g. 3MF files)
      projectOnly: "#D2BCFF", // the boxed "Project only" tag: an STL or 3MF a project keeps for itself
      green: "#7AD99B", greenDim: "#1B3A29", greenBorder: "#2F6B49",
      danger: "#FF8F85", dangerDim: "#40201E",
      onAccent: "#1B0F3A", onTeal: "#04201E", onDanger: "#2B0A07",
    },
  },
  {
    id: "light",
    name: "Light",
    note: "Dark text on a light background",
    mode: "light",
    colors: {
      bg: "#F2F3F4", panel: "#FFFFFF", panelAlt: "#F0F1F2", panelHover: "#E6E8EA",
      border: "#D3D6D9", borderStrong: "#AEB4B9",
      textPrimary: "#16181A", textMuted: "#3A4045", textFaint: "#566066", heading: "#000000",
      amber: "#9A5600", amberDim: "#FBE6C8", amberBorder: "#E1B070",
      teal: "#1C737C", tealDim: "#DDF1F3", tealBorder: "#8CC3C8",
      fileName: "#1A5FB4", // file names (e.g. 3MF files)
      projectOnly: "#6B2FC9", // the boxed "Project only" tag: an STL or 3MF a project keeps for itself
      green: "#1E7432", greenDim: "#D7EFDC", greenBorder: "#8CCB99",
      danger: "#B3342A", dangerDim: "#FADDDA",
      onAccent: "#FFFFFF", onTeal: "#FFFFFF", onDanger: "#FFFFFF",
    },
  },
];

// A 3MF's settings window wears the colours of the slicer that made it, dark or light to match the scheme in use:
// PrusaSlicer's orange, OrcaSlicer's teal green. `accent` is the slicer's own colour, for fills (tick boxes, the
// selected tab's underline); `accentText` is the shade of it that's legible as text and icons on `bg` and on
// `accentDim` (the selected page). `field` is the box a value sits in.
export const SLICER_SCHEMES = {
  prusa: {
    dark: {
      bg: "#2B2B2D", field: "#3A3A3D", border: "#4E4E52", borderStrong: "#6E6E73",
      heading: "#FFFFFF", textPrimary: "#EDEDED", textMuted: "#C9C9CC", textFaint: "#A9A9AE",
      accent: "#ED6B21", accentText: "#F3874A", accentDim: "#4A2F1F",
    },
    light: {
      bg: "#FFFFFF", field: "#F4F4F4", border: "#D2D2D2", borderStrong: "#A2A2A2",
      heading: "#000000", textPrimary: "#1A1A1A", textMuted: "#3C3C3C", textFaint: "#5C5C5C",
      accent: "#ED6B21", accentText: "#AD4A0F", accentDim: "#FDE8DB",
    },
  },
  orca: {
    dark: {
      bg: "#2D2D31", field: "#38383E", border: "#4A4A51", borderStrong: "#6B6B74",
      heading: "#FFFFFF", textPrimary: "#EFEFF0", textMuted: "#C9C9CE", textFaint: "#A8A8AF",
      accent: "#009688", accentText: "#2EBBAB", accentDim: "#16403C",
    },
    light: {
      bg: "#FFFFFF", field: "#F5F5F6", border: "#DBDBDB", borderStrong: "#ABABAB",
      heading: "#262E30", textPrimary: "#262E30", textMuted: "#454D50", textFaint: "#5E6668",
      accent: "#009688", accentText: "#00796B", accentDim: "#E2F3F1",
    },
  },
};

// Colours that are the same in every scheme, because of what they sit on or stand for: a model's preview is drawn on
// white, a camera's picture is shown on black (with its labels and messages over it), a dialog dims the page behind it,
// and the version stars are real metals (silver for v1, gold for the starred one), each with a darker edge so it holds
// up on light backgrounds.
export const FIXED = {
  preview: "#FFFFFF", previewIcon: "#C7CACC",
  camera: "#000000", cameraText: "#E6E8EA", cameraMessage: "#8A9198", cameraBadge: "rgba(0,0,0,0.55)",
  backdrop: "rgba(0,0,0,0.55)", shadow: "rgba(0,0,0,0.3)",
  gold: "#F2C230", goldEdge: "#B8860B", silver: "#C9CDD3", silverEdge: "#868B93",
  voronRed: "#ED3023", // Voron Design's red (as in the sidebar's Voron heart): the top bar's warning
};

export const FONTS = [
  { id: "archivo", name: "Archivo", note: "default", stack: "'Archivo', system-ui, sans-serif" },
  { id: "system", name: "System", note: "your device's own font", stack: "system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif" },
  { id: "verdana", name: "Verdana", note: "wide, easy to read", stack: "Verdana, Geneva, 'DejaVu Sans', sans-serif" },
  { id: "arial", name: "Arial", note: "plain and familiar", stack: "Arial, Helvetica, 'Liberation Sans', sans-serif" },
  { id: "play", name: "Play", note: "sharp and techy", stack: "'Play', system-ui, sans-serif" },
  { id: "mono", name: "Monospace", note: "fixed width", stack: "'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace" },
];

export const SIZES = [
  { id: "small", name: "Small", scale: 0.9 },
  { id: "default", name: "Default", scale: 1 },
  { id: "large", name: "Large", scale: 1.12 },
  { id: "xlarge", name: "Extra large", scale: 1.25 },
];

// file_name_color: the colour of 3MF file names — "auto" (the scheme's own fileName blue) or a #RRGGBB chosen
export const DEFAULT_APPEARANCE = { scheme: "farmhand", contrast: 0, font: "archivo", size: "default", file_name_color: "auto" };

// Ready-made choices for the 3MF file name colour (any colour can also be picked)
export const FILE_NAME_COLORS = [
  { id: "#4A90E2", name: "Blue" },
  { id: "#5AC8FA", name: "Sky" },
  { id: "#3CB4A8", name: "Teal" },
  { id: "#5CB85C", name: "Green" },
  { id: "#E6C229", name: "Yellow" },
  { id: "#F08A24", name: "Orange" },
  { id: "#E66AA8", name: "Pink" },
  { id: "#9B7BE0", name: "Purple" },
];
