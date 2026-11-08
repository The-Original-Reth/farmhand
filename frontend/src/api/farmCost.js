// The Farm cost page: each printer's filament by month, and where each month's record is saved.
import { jsonBody, request, timeZone } from "./client.js";

// The Farm cost page's filament: { printers: [{ printer_id, months: [{ key: "2026-10", prints, grams, filament_cost,
// unweighed, uncosted }] }] }, months newest first, totalled in this browser's time zone; records: { folder, problem,
// saved: [file names, newest first] }, where each month's record is saved once it's over
export const getFarmCost = () => request(`/farm-cost${timeZone ? `?tz=${encodeURIComponent(timeZone)}` : ""}`);

// Where each month's Farm cost record is saved (Settings): { path, isDefault, defaultPath, status: { exists,
// writable, markerOk, ready } }. setFarmCostLocation(null) goes back to the default; a folder that can't be used is
// refused with the reason.
const normalizeFarmCostLocation = (l) => ({
  path: l.path,
  isDefault: l.is_default,
  defaultPath: l.default_path,
  status: { exists: l.status.exists, writable: l.status.writable, markerOk: l.status.marker_ok, ready: l.status.ready },
});

export const getFarmCostLocation = async () => normalizeFarmCostLocation(await request("/farm-cost/location"));

export const setFarmCostLocation = async (path) =>
  normalizeFarmCostLocation(await request("/farm-cost/location", jsonBody("PUT", { path })));
