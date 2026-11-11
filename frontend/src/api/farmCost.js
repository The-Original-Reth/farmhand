// The Farm cost page: each printer's filament by month, and where each month's record is saved.
import { jsonBody, normalizeFolderLocation, request, tzQuery } from "./client.js";

// The Farm cost page's filament: { printers: [{ printer_id, months: [{ key: "2026-10", prints, grams, filament_cost,
// unweighed, uncosted }] }] }, months newest first, totalled in this browser's time zone; records: { folder, problem,
// saved: [file names, newest first] }, where each month's record is saved once it's over
export const getFarmCost = () => request(`/farm-cost${tzQuery}`);

// Where each month's Farm cost record is saved (Settings): { path, isDefault, defaultPath, status: { exists,
// writable, markerOk, ready } }. setFarmCostLocation(null) goes back to the default; a folder that can't be used is
// refused with the reason.
export const getFarmCostLocation = async () => normalizeFolderLocation(await request("/farm-cost/location"));

export const setFarmCostLocation = async (path) =>
  normalizeFolderLocation(await request("/farm-cost/location", jsonBody("PUT", { path })));
