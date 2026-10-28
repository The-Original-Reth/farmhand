import { readStored, writeStored } from "../lib/storage.js";

// Each option's `dir` is the natural direction when it's first picked (newest first, most first, A→Z)
export const MODEL_SORTS = [
  { key: "name", label: "Name", dir: "asc" },
  { key: "added", label: "Date added", dir: "desc" },
  { key: "threemf", label: "3MF files", dir: "desc" },
  { key: "printers", label: "Printers", dir: "desc" },
  { key: "type", label: "Type", dir: "asc" },
];
const SORT_STORAGE_KEY = "farmhand.modelSort";
export const nameCollator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" }); // "Part 2" before "Part 10"

// Anything unrecognised (an old or hand-edited value) becomes the default
export function normalizeModelSort(saved) {
  if (MODEL_SORTS.some((o) => o.key === saved?.key) && (saved.dir === "asc" || saved.dir === "desc")) {
    return { key: saved.key, dir: saved.dir };
  }
  return { key: "name", dir: "asc" };
}

// What this browser remembers: shown straight away, then replaced by the server's copy when that arrives
export function loadModelSort() {
  return normalizeModelSort(readStored(SORT_STORAGE_KEY));
}

export function saveModelSort(sort) {
  writeStored(SORT_STORAGE_KEY, sort);
}

// rows: [{ m, bundleCount, printerCount }]. Ties always fall back to name A→Z, so the order is stable.
export function sortModelRows(rows, { key, dir }) {
  const sign = dir === "desc" ? -1 : 1;
  const byName = (a, b) => nameCollator.compare(a.m.name, b.m.name) || a.m.id - b.m.id;
  const primary = {
    name: (a, b) => nameCollator.compare(a.m.name, b.m.name),
    added: (a, b) => (Date.parse(a.m.created) || 0) - (Date.parse(b.m.created) || 0) || a.m.id - b.m.id,
    threemf: (a, b) => a.bundleCount - b.bundleCount,
    printers: (a, b) => a.printerCount - b.printerCount,
    type: (a, b) => nameCollator.compare(a.m.type, b.m.type),
  }[key];
  return [...rows].sort((a, b) => sign * primary(a, b) || byName(a, b));
}
