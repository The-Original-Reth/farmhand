import { readStored, writeStored } from "../lib/storage.js";

// The Printers page's order: a column and "asc" | "desc". Saved on the server with the rest of the settings; this
// browser keeps a copy only to show it at once, before the server has answered.
export const PRINTER_SORTS = { name: "Name", kind: "Type", wired: "Wired IP", wireless: "Wireless IP" }; // the columns
export const DEFAULT_PRINTER_SORT = { key: "name", dir: "asc" };
const KEY = "farmhand.printerSort";

export const normalizePrinterSort = (s) =>
  PRINTER_SORTS[s?.key] && (s.dir === "asc" || s.dir === "desc") ? { key: s.key, dir: s.dir } : DEFAULT_PRINTER_SORT;

// An older Farmhand kept just "asc" or "desc", for the name
export function loadPrinterSort() {
  const raw = readStored(KEY);
  if (raw === "asc" || raw === "desc") return { key: "name", dir: raw };
  return normalizePrinterSort(raw);
}

export const savePrinterSort = (s) => writeStored(KEY, s);
