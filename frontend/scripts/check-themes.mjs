// Checks that every colour scheme is legible: WCAG contrast ratios for text on the surfaces it sits on.
// Run:  node scripts/check-themes.mjs          (exits non-zero if a scheme fails)
import { FIXED, PRESETS, SLICER_SCHEMES } from "../src/palettes.js";

const lum = (hex) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
export const ratio = (a, b) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

const MIN = 4.5; // WCAG AA for normal-size text
let failures = 0;
for (const p of PRESETS) {
  const c = p.colors;
  const checks = [
    ...["bg", "panel", "panelAlt", "panelHover"].flatMap((s) => ["heading", "textPrimary", "textMuted", "textFaint"].map((t) => [`${t} on ${s}`, c[t], c[s]])),
    ["accent on panel", c.amber, c.panel], ["accent on its chip", c.amber, c.amberDim],
    ["secondary on panel", c.teal, c.panel], ["secondary on its chip", c.teal, c.tealDim],
    ["green on panel", c.green, c.panel], ["green on its chip", c.green, c.greenDim],
    ["danger on panel", c.danger, c.panel],
    ["project only tag on panel", c.projectOnly, c.panel], ["project only tag on a heading", c.projectOnly, c.panelAlt],
    ["text on accent button", c.onAccent, c.amber], ["text on secondary", c.onTeal, c.teal], ["text on danger button", c.onDanger, c.danger],
  ];
  const bad = checks.filter(([, fg, bg]) => ratio(fg, bg) < MIN);
  const worst = checks.reduce((m, [n, fg, bg]) => (ratio(fg, bg) < m[0] ? [ratio(fg, bg), n] : m), [99, ""]);
  const accentVsSecondary = ratio(c.amber, c.teal);
  const tag = p.classic ? " (original look, not held to the check)" : "";
  console.log(`${bad.length && !p.classic ? "FAIL" : "ok  "} ${p.name.padEnd(14)} weakest: ${worst[1]} at ${worst[0].toFixed(1)}:1${tag}`);
  if (!p.classic) {
    bad.forEach(([n, fg, bg]) => console.log(`        ${n}: ${fg} on ${bg} = ${ratio(fg, bg).toFixed(2)}:1 (needs ${MIN})`));
    if (bad.length) failures++;
  }
  // the accent and secondary are the two sides of every comparison: they must not be mistaken for each other
  if (!p.classic && Math.abs(lum(c.amber) - lum(c.teal)) < 0.02 && c.amber.slice(1, 3) === c.teal.slice(1, 3)) { console.log("        accent and secondary look alike"); failures++; }
}
// The slicers' own colours, worn by a 3MF's settings window (dark and light)
for (const [slicer, modes] of Object.entries(SLICER_SCHEMES)) {
  for (const [mode, s] of Object.entries(modes)) {
    const checks = [
      ...["bg", "field"].flatMap((b) => ["heading", "textPrimary", "textMuted", "textFaint"].map((t) => [`${t} on ${b}`, s[t], s[b]])),
      ["accent text on bg", s.accentText, s.bg], ["accent text on the selected page", s.accentText, s.accentDim],
    ];
    const bad = checks.filter(([, fg, bg]) => ratio(fg, bg) < MIN);
    const worst = checks.reduce((m, [n, fg, bg]) => (ratio(fg, bg) < m[0] ? [ratio(fg, bg), n] : m), [99, ""]);
    console.log(`${bad.length ? "FAIL" : "ok  "} ${`${slicer} ${mode}`.padEnd(14)} weakest: ${worst[1]} at ${worst[0].toFixed(1)}:1`);
    bad.forEach(([n, fg, bg]) => console.log(`        ${n}: ${fg} on ${bg} = ${ratio(fg, bg).toFixed(2)}:1 (needs ${MIN})`));
    if (bad.length) failures++;
  }
}
// The colours no scheme changes: a camera's labels and messages over its black picture
for (const [n, fg, bg] of [["camera label on camera", FIXED.cameraText, FIXED.camera], ["camera message on camera", FIXED.cameraMessage, FIXED.camera]]) {
  const r = ratio(fg, bg);
  console.log(`${r < MIN ? "FAIL" : "ok  "} ${n} at ${r.toFixed(1)}:1`);
  if (r < MIN) failures++;
}
console.log(failures ? `\n${failures} scheme(s) not legible enough` : "\nevery scheme is legible");
process.exit(failures ? 1 : 0);
