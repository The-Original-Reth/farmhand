import { CircleDot, Puzzle, StickyNote } from "lucide-react";

// The parts the slicer layouts (boss.js, orca.js) are built from, and the questions asked of them: which keys a page
// has a place for, which pages have anything to show. Drawing them is fields.jsx's job.
//
// A page: { id, title, Icon, groups: [{ title, rows: [[key, label, kind or unit]], limits? }], extruder?, render? }.

// Text settings are saved with \n, \\ and \" escapes in a PrusaSlicer 3MF
export const unescape = (v) => String(v).replace(/\\(.)/g, (_, ch) => (ch === "n" ? "\n" : ch === "t" ? "\t" : ch));
// A preset's name as the slicer's drop-down shows it, without the escapes and quotes it's saved with
export const presetName = (v) => unescape(v || "").replace(/^"|"$/g, "");
// One value of a per-extruder (or per-filament) setting: they're kept joined, by ";" when the values hold commas
export const nth = (raw, index) => {
  if (raw == null || index == null) return raw;
  const parts = String(raw).split(String(raw).includes(";") ? ";" : ",");
  return parts[index] ?? parts[0];
};
// "Ripe_PLA" -> "Ripe PLA": a setting no page has a place for gets its key as a label
export const keyLabel = (k) => k.replace(/_/g, " ").replace(/^./, (ch) => ch.toUpperCase());

// The keys in some groups, on a page, and on a list of pages
export const groupKeys = (groups) => groups.flatMap((g) => g.rows.map((r) => r[0]));
export const pageKeys = (page) => groupKeys(page.groups || []);
export const placedKeys = (pages) => new Set(pages.flatMap(pageKeys));

// How many extruders the printer has, by how many nozzle diameters there are
export const extruderCount = (settings) => Math.max(1, String(settings?.nozzle_diameter ?? "").split(/[;,]/).filter((s) => s !== "").length);
// One Extruder page per extruder, each reading its own extruder's values
export const extruderPages = (count, groups) =>
  Array.from({ length: count }, (_, i) => ({ id: `extruder${i}`, title: `Extruder ${i + 1}`, Icon: CircleDot, groups, extruder: i }));
// A setting as a page shows it: on an Extruder page, the page's own extruder's value of a `perExtruder` key
export const pageValue = (settings, perExtruder) => (key, page) => {
  const raw = settings?.[key];
  return page?.extruder != null && perExtruder.has(key) ? nth(raw, page.extruder) : raw;
};
// A Notes page: the one text box
export const notesPage = (key) => ({ id: "notes", title: "Notes", Icon: StickyNote, groups: [{ title: "Notes", rows: [[key, "", "gcode"]] }] });
// "Other": the settings that `belongs` to a tab and none of `pages` has a place for (all the tabs' pages, so none
// shows twice), so none is lost
export const otherPage = (settings, pages, belongs, title = "More settings in this 3MF") => {
  const placed = placedKeys(pages);
  const rest = Object.keys(settings).filter((k) => !placed.has(k) && belongs(k)).sort();
  return rest.length ? [{ id: "other", title: "Other", Icon: Puzzle, groups: [{ title, rows: rest.map((k) => [k, keyLabel(k)]) }] }] : [];
};

// `has(key, page)`: whether a page shows a setting's row. By default, whether the file has a value for it there.
export const hasValue = (value) => (key, page) => value(key, page) !== undefined;
// The rows of a group that `has` shows on `page`
export const shownRows = (group, has, page) => group.rows.filter(([key]) => has(key, page));
// The pages with something to show (a page of Farmhand's own, with `render`, always has)
export const pagesWithContent = (pages, has) => pages.filter((p) => p.render || (p.groups || []).some((g) => shownRows(g, has, p).length));
