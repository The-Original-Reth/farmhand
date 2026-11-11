// Printers: adding and editing them, their printer profiles and parts, their Moonraker / PrusaLink (status, print
// history, cameras, energy, the 1500-hour service, maintenance) and their notes.
import { del, formBody, jsonBody, notesBody, post, request, timeZone, tzQuery } from "./client.js";

export const normalizePrinter = (p) => ({
  id: p.id,
  name: p.name,
  kind: p.kind || "",
  wired: p.wired_ip,
  wireless: p.wireless_ip,
  decommissioned: p.decommissioned,
  notes: p.notes || "", // free text about the printer
  notesRevision: p.notes_revision || 0, // names one exact version of the text: a save is refused if it has moved on
  notesUpdatedAt: p.notes_updated_at || null,
  moonrakerUrl: p.moonraker_url || null, // where Farmhand reaches its Moonraker (set, else <IP>:7125)
  moonrakerUrlOverride: p.moonraker_url_override || null, // only what was set for it
  mainsailUrl: p.mainsail_url || null,
  hasMoonrakerApiKey: !!p.has_moonraker_api_key, // the key itself never comes back
  connectionType: p.connection_type || "moonraker", // "moonraker" (Klipper) | "prusalink" (Prusa Core One, MK4, XL...)
  prusalinkUrl: p.prusalink_url || null, // where Farmhand reaches its PrusaLink (set, else http://<IP>)
  prusalinkUrlOverride: p.prusalink_url_override || null,
  prusalinkUsername: p.prusalink_username || "maker",
  hasPrusalinkPassword: !!p.has_prusalink_password, // the password itself only comes from getPrusaLinkPassword
  cameraAddress: p.camera_address || null, // a camera Farmhand plays itself (a Buddy3D's): its IP, or an rtsp:// URL
  // its printer presets in the slicer, A to Z: [{ id, name, aliases, settingsCopiedFrom }]; settingsCopiedFrom: a copy's
  // original, whose printer settings it was copied with (null for one that isn't a copy, or got none)
  subPrinters: (p.sub_printers || []).map((s) => ({ ...s, settingsCopiedFrom: s.settings_copied_from || null })),
  defaultSubPrinterId: p.default_sub_printer_id ?? null, // the one its uploads start on (null: Farmhand guesses)
  // The 1500-hour service reminder Farmhand keeps: { state: waiting | off | ok | due, enabled, interval_hours,
  // hours_since, started_at, last_done: { done_at, hours, note } | null }
  service: p.service || {
    state: "waiting", enabled: true, interval_hours: 1500, hours_since: null, started_at: null, last_done: null,
    notes: "", notes_revision: 0, notes_updated_at: null,
  },
});

// A preview's address ends in ?r=<its revision> (when it was drawn; a 3MF version's never changes), so the address
// changes whenever the picture does and the browser can keep each one for good instead of asking again every time.

export const getPrinters = () => request("/printers");

// The range a scan starts with: the /24 of the network the server is on ("192.168.10.0/24"), or "" when it can't tell
export const getDiscoverRange = async () => (await request("/printers/discover/range")).cidr || "";

// The printers in a network range (e.g. "192.168.1.0/24") that aren't in Farmhand yet. Nothing is added; `signal`
// lets the dialog stop waiting (the scan itself runs to its end on the server).
export const discoverPrinters = async (cidr, { signal } = {}) =>
  (await request(`/printers/discover?cidr=${encodeURIComponent(cidr)}`, { signal })).map((f) => ({
    ip: f.ip,
    hostname: f.hostname || "",
    connectionType: f.connection_type,
    address: f.address,
    webUrl: f.web_url || null,
    firmware: f.firmware || null, // "Klipper" | "Kalico" | "Prusa"; null when it wouldn't say
    version: f.version || null,
    state: f.state || null,
    needsApiKey: !!f.needs_api_key, // it wants its login: Moonraker's API key, or PrusaLink's password
    link: f.link || null, // how `ip` reached it: "wired" | "wireless"; null when it couldn't tell
    wiredIp: f.wired_ip || null, // a printer on both is found once, at its wired IP, with both of these
    wirelessIp: f.wireless_ip || null,
    // the decommissioned printer in Farmhand at one of its addresses: picking it brings that one back
    decommissionedId: f.decommissioned_id ?? null,
    decommissionedName: f.decommissioned_name || null,
  }));

// The connection (Mainsail / Moonraker or PrusaLink) can be given straight away, with the same fields as updatePrinter
export const createPrinter = ({
  name, kind, wiredIp, wirelessIp, connectionType, moonrakerUrl, moonrakerApiKey, prusalinkUrl, prusalinkUsername, prusalinkPassword,
  cameraAddress,
}) =>
  request("/printers", jsonBody("POST", {
    name,
    kind: kind || null,
    wired_ip: wiredIp || null,
    wireless_ip: wirelessIp || null,
    connection_type: connectionType || "moonraker",
    ...(moonrakerUrl ? { moonraker_url: moonrakerUrl } : {}),
    ...(moonrakerApiKey ? { moonraker_api_key: moonrakerApiKey } : {}),
    ...(prusalinkUrl ? { prusalink_url: prusalinkUrl } : {}),
    ...(prusalinkUsername ? { prusalink_username: prusalinkUsername } : {}),
    ...(prusalinkPassword ? { prusalink_password: prusalinkPassword } : {}),
    ...(cameraAddress ? { camera_address: cameraAddress } : {}),
  }));

// moonrakerUrl: blank = the default (<IP>:7125). moonrakerApiKey: undefined keeps the saved key, "" removes it.
// connectionType: "moonraker" | "prusalink". prusalinkUrl: blank = http://<IP>. prusalinkPassword works like the API key.
// cameraAddress: blank removes the camera.
export const updatePrinter = (
  id,
  {
    name, kind, wiredIp, wirelessIp, decommissioned, moonrakerUrl, moonrakerApiKey, connectionType, prusalinkUrl, prusalinkUsername,
    prusalinkPassword, cameraAddress,
  },
) =>
  // Blank optional fields are sent as null so they actually clear
  request(`/printers/${id}`, jsonBody("PATCH", {
    name,
    kind: kind || null,
    wired_ip: wiredIp || null,
    wireless_ip: wirelessIp || null,
    decommissioned: !!decommissioned,
    ...(moonrakerUrl !== undefined ? { moonraker_url: moonrakerUrl || null } : {}),
    ...(moonrakerApiKey !== undefined ? { moonraker_api_key: moonrakerApiKey } : {}),
    ...(connectionType !== undefined ? { connection_type: connectionType } : {}),
    ...(prusalinkUrl !== undefined ? { prusalink_url: prusalinkUrl || null } : {}),
    ...(prusalinkUsername !== undefined ? { prusalink_username: prusalinkUsername } : {}),
    ...(prusalinkPassword !== undefined ? { prusalink_password: prusalinkPassword } : {}),
    ...(cameraAddress !== undefined ? { camera_address: cameraAddress || null } : {}),
  }));

// Only a decommissioned printer with no 3MF files kept for it (409 otherwise, saying why)
export const deletePrinter = (id) => del(`/printers/${id}`);

// ---- a printer's printer profiles: its printer presets in the slicer (found from its 3MFs, or added here). Each
// resolves to the whole printer as it now stands. 409 when the printer already has one by that name. ----
const subPrinterPath = (printerId, subPrinterId) => `/printers/${printerId}/sub-printers/${subPrinterId}`;

export const addSubPrinter = (printerId, name) => request(`/printers/${printerId}/sub-printers`, jsonBody("POST", { name }));

// a new printer profile with a copy of its parts and printer settings, called `name` (its 3MFs and being the default
// stay with the original)
export const copySubPrinter = (printerId, subPrinterId, name) =>
  request(`${subPrinterPath(printerId, subPrinterId)}/copy`, jsonBody("POST", { name }));

export const renameSubPrinter = (printerId, subPrinterId, name) =>
  request(subPrinterPath(printerId, subPrinterId), jsonBody("PATCH", { name }));

// the one its uploads start on, whatever preset a 3MF was sliced with; null: none (Farmhand guesses from the preset)
export const setDefaultSubPrinter = (printerId, subPrinterId) =>
  request(`/printers/${printerId}/default-sub-printer`, jsonBody("PUT", { sub_printer_id: subPrinterId }));

// its 3MFs stay, with no printer profile; its parts go
export const deleteSubPrinter = (printerId, subPrinterId) => del(subPrinterPath(printerId, subPrinterId));

// A printer profile's parts (its Printer parts page): [{ id, part, make, model, installedOn: "2026-08-14" | null, note,
// inName }].
// Saving resolves to the whole list as it now stands.
const normalizePart = (p) => ({
  id: p.id, part: p.part, make: p.make || "", model: p.model || "", installedOn: p.installed_on || null, note: p.note || "",
  inName: !!p.in_name, // ticked "Add to name"
});

const partBody = ({ part, make, model, installedOn, note, inName }) => ({
  part, make: make || null, model: model || null, installed_on: installedOn || null, note: note || null, in_name: !!inName,
});

const partsPath = (printerId, subPrinterId) => `${subPrinterPath(printerId, subPrinterId)}/parts`;

const partsList = async (call) => (await call).map(normalizePart);

export const getSubPrinterParts = (printerId, subPrinterId) => partsList(request(partsPath(printerId, subPrinterId)));

// A copied printer profile's printer settings, as its original had them: { copiedFrom, fromFile, copiedAt, settings }
export const getSubPrinterSettingsCopy = async (printerId, subPrinterId) => {
  const r = await request(`${subPrinterPath(printerId, subPrinterId)}/settings-copy`);
  return { copiedFrom: r.copied_from, fromFile: r.from_file || null, copiedAt: r.copied_at || null, settings: r.settings || {} };
};

// The whole list at once, as the page was edited: a part with an id is changed, one without is added, and one left out
// is removed (`removes`: the list leaves some out, which the API wants confirmed). All of it, or nothing.
export const saveSubPrinterParts = (printerId, subPrinterId, parts, removes) =>
  partsList(request(`${partsPath(printerId, subPrinterId)}${removes ? "?confirm=true" : ""}`, jsonBody("PUT", parts.map((p) => ({ id: p.id ?? null, ...partBody(p) })))));

// ---- a PrusaLink printer (Prusa Core One...): live status and sending it a print. Its history, statistics, service
// and maintenance use the same calls as a Moonraker printer's (below); its maintenance is kept in Farmhand. ----

// { reachable, error, error_kind, state, printer_type, firmware, temps: { temp_nozzle, target_nozzle, temp_bed,
//   target_bed }, job: { id, state, file, progress, time_printing, time_remaining } | null, last_sync_at, totals }
// Asking also brings Farmhand's record of its prints up to date.
export const getPrusaLinkStatus = (printerId) => request(`/printers/${printerId}/prusalink`);

// The PrusaLink password saved for it (null when none is): asked for only when it's to be shown
export const getPrusaLinkPassword = async (printerId) => (await request(`/printers/${printerId}/prusalink/password`)).password;

// A sliced .bgcode / .gcode: put on the printer's USB drive and printed. 409 while the printer is busy.
export const sendPrint = (printerId, file) => request(`/printers/${printerId}/prusalink/print`, formBody("POST", { file }));

// ---- a printer's Moonraker: connection, print history (Farmhand's copy), statistics, maintenance ----
// A printer that can't be reached answers 502 with { detail, kind } (no_address | unreachable | unauthorized | ...).

// { reachable, klippy_state, moonraker_version, error, error_kind, print: { state: printing | paused, file, progress
//   (0-100), print_duration, time_remaining, extruder, heater_bed } | null, last_sync_at, totals, ... }
export const getMoonrakerStatus = (printerId) => request(`/printers/${printerId}/moonraker`);

export const syncPrinterHistory = (printerId) => post(`/printers/${printerId}/moonraker/sync`);

export const getPrintStats = (printerId) => request(`/printers/${printerId}/print-stats`);

// A printer's cameras as set up in Mainsail, for the Monitor page: { webcams: [{ name, service, mjpeg, stream_url,
// snapshot_url, flip_horizontal, flip_vertical, rotation, aspect_ratio }], error }. Never fails: error says why there are none.
// ...and board: the computer a Klipper printer runs on, { name: "Pi 4" | "CM4" | ..., model, memory_gb }, or null
export const getWebcams = (printerId) => request(`/printers/${printerId}/webcams`);

// How far along the print running now is: { state: "printing" | "paused" | null, progress: 0-100 | null, file, error }
export const getPrintProgress = (printerId) => request(`/printers/${printerId}/progress`);

// { meter: { sensor, energy_kwh, taken_at, first_reading_at } | null, print_total_kwh, print_jobs_kwh,
//   months: [{ key: "2026-10", prints, print_count, whole, partial }] } — totalled by the server in this browser's
//   time zone (a year is its months added up)
export const getEnergy = (printerId) =>
  request(`/printers/${printerId}/energy${tzQuery}`);

// status: "" (all) | "completed" | "failed" | "cancelled" | "error" | ...; q: words that must all be in the file name.
// Each job has filament_grams (the filament used in grams; null when no density or slicer estimate is known),
// filament_cost (null when there's no price for it) and filament_cost_detail: { cost, grams, cost_per_kg,
// density, diameter, source: "gcode" | "3mf", filename, bundle_id, version_id, version } | null; energy_cost: its
// energy_kwh at the Power page's price per kWh (null without either); total_cost: filament_cost + energy_cost (the
// filament cost alone without an energy cost; null or 0 when the filament cost is). The answer also has
// energy_price_per_kwh.
export const getPrintJobs = (printerId, { limit = 25, offset = 0, status = "", q = "" } = {}) => {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (status) params.set("status", status);
  if (q.trim()) params.set("q", q.trim());
  if (timeZone) params.set("tz", timeZone); // which month a print's energy is priced in
  return request(`/printers/${printerId}/print-jobs?${params}`);
};

// The 1500-hour service lives in Farmhand. Both resolve to the printer as it now stands.
export const serviceDone = (printerId, { note }) => request(`/printers/${printerId}/service/done`, jsonBody("POST", { note }));

export const setServiceEnabled = (printerId, enabled) => request(`/printers/${printerId}/service`, jsonBody("PATCH", { enabled }));

// Notes kept with the service: the same rules as other notes (a save names the revision it started from; 409 if moved
// on). Resolves to the printer (as .printer); NotesSection reads `notes` / `notes_revision` from what onSave returns, hence the reshape.
export const saveServiceNotes = async ({ printerId, notes, baseRevision }) => {
  const p = await request(`/printers/${printerId}/service/notes`, notesBody(notes, baseRevision));
  return { notes: p.service.notes, notes_revision: p.service.notes_revision, printer: p };
};

// Maintenance lives in the printer's Moonraker, in Mainsail's own format: Mainsail shows the same list. A PrusaLink
// printer's is kept in Farmhand, in the same format (no filament reminders: it doesn't report filament use).
// reminder: { type: null | "one-time" | "repeat", filament / printtime / date: { bool, value } } in metres / hours / days
export const getMaintenance = (printerId) => request(`/printers/${printerId}/maintenance`);

export const addMaintenance = (printerId, { name, note, reminder }) =>
  request(`/printers/${printerId}/maintenance`, jsonBody("POST", { name, note, reminder }));

export const updateMaintenance = (printerId, entryId, { name, note, reminder }) =>
  request(`/printers/${printerId}/maintenance/${encodeURIComponent(entryId)}`, jsonBody("PUT", { name, note, reminder }));

export const performMaintenance = (printerId, entryId, { note }) =>
  request(`/printers/${printerId}/maintenance/${encodeURIComponent(entryId)}/done`, jsonBody("POST", { note }));

export const deleteMaintenance = (printerId, entryId) => del(`/printers/${printerId}/maintenance/${encodeURIComponent(entryId)}`);

// ---- notes about a printer (the same rules as a model's: a save names the revision it started from) ----
export const savePrinterNotes = ({ printerId, notes, baseRevision }) =>
  request(`/printers/${printerId}/notes`, notesBody(notes, baseRevision));
