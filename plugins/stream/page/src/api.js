// The Stream plugin page's one HTTP client, as Farmhand's src/api.js is for Farmhand's: the Stream page's calls
// (api/stream.js, copied from Farmhand's), and the few the plugin answers in place of Farmhand's own API: the farm's
// printers and cameras, each printer's print, a camera's picture for the preview, the saved layouts, and bringing
// Farmhand's Stream page set-up over.
import { API_BASE, jsonBody, post, request } from "./api/client.js";

export * from "./api/stream.js";
export { errorText } from "./api/client.js";

// The farm as the plugin last heard it from Farmhand: { printers: [{ id, name }], cameras: { printer id: { webcams,
// error } }, farmhand_error }. Asked once for every printer at a time (the page asks each printer's cameras).
let farmAsked = null;
export const getFarm = () => {
  if (!farmAsked || Date.now() - farmAsked.at > 5000) {
    const promise = request("/farm");
    farmAsked = { at: Date.now(), promise };
    promise.catch(() => (farmAsked = null));
  }
  return farmAsked.promise;
};

// A printer's cameras, as Monitor's getWebcams gives them: { webcams: [{ name, printer_id, rotation, ... }], error }
export const getWebcams = async (printerId) => {
  const farm = await getFarm();
  const mine = farm.cameras[String(printerId)] || { webcams: [], error: "Farmhand doesn't list this printer." };
  return { ...mine, webcams: mine.webcams.map((w) => ({ ...w, printer_id: printerId })) };
};

// How far along the print running now is: { state: "printing" | "paused" | null, progress, file, error }
export const getPrintProgress = (printerId) => request(`/printers/${printerId}/progress`);

// A camera's latest picture, for the preview (the plugin gives it: its feeder's while live, its snapshot otherwise)
export const cameraPictureUrl = (printerId, name) => `${API_BASE}/cameras/${printerId}/${encodeURIComponent(name)}/picture`;

// The saved layouts, kept by the plugin (Farmhand kept them in its settings)
export const getLayouts = async () => (await request("/layouts")).layouts;
export const saveLayouts = async (layouts) => (await request("/layouts", jsonBody("PUT", { layouts }))).layouts;

// Farmhand's own Stream page set-up, brought over once: { done: { at, stream_folder } | null, own_settings }
export const getMigration = () => request("/migrate");
export const migrateNow = (replace = false) => request("/migrate", jsonBody("POST", { replace }));
export { post };
