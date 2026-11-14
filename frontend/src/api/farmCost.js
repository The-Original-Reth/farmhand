// The Farm cost page: each printer's filament by month, and where each month's record is saved.
import { jsonBody, normalizeFolderLocation, request, tzQuery } from "./client.js";

// The Farm cost page's filament: { printers: [{ printer_id, months: [{ key: "2026-10", prints, grams, filament_cost,
// unweighed, uncosted, estimated }], days }] }, months newest first, totalled in this browser's time zone (estimated:
// how many prints' filament in them is the slicer's estimate, a PrusaLink printer's; 0 from a server that doesn't
// say); records: { folder, problem, saved: [file names, newest first] }, where each month's record is saved once it's over
const withEstimated = (rows) => (rows || []).map((m) => ({ ...m, estimated: m.estimated || 0 }));
export const getFarmCost = async () => {
  const r = await request(`/farm-cost${tzQuery}`);
  return {
    ...r,
    printers: (r.printers || []).map((p) => ({ ...p, months: withEstimated(p.months), days: withEstimated(p.days) })),
  };
};

// Where each month's Farm cost record is saved (Settings): { path, isDefault, defaultPath, status: { exists,
// writable, markerOk, ready } }. setFarmCostLocation(null) goes back to the default; a folder that can't be used is
// refused with the reason.
export const getFarmCostLocation = async () => normalizeFolderLocation(await request("/farm-cost/location"));

export const setFarmCostLocation = async (path) =>
  normalizeFolderLocation(await request("/farm-cost/location", jsonBody("PUT", { path })));
