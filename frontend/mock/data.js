// The mockup's sample farm: printers, models, 3MF files, print history, energy, maintenance and notes, shaped
// exactly like the real API's answers. Generated from a fixed seed, so it's the same every time the mockup starts.
// The 3MF settings and preview images are real (from the project's sample files, see fixtures/).
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
export const FIXTURES = join(here, "fixtures");
const settingsFixture = (slug) => JSON.parse(readFileSync(join(FIXTURES, `settings-${slug}.json`), "utf-8"));

// A small seeded random number generator (mulberry32): the same farm on every start
function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const HOUR = 3600;
export const DAY = 86400;
// A time as the API writes it (UTC, "+00:00"); null stays null
export const iso = (unix) => (unix == null ? null : new Date(unix * 1000).toISOString().replace("Z", "+00:00"));
const NOW = Math.floor(Date.now() / 1000);

// The parts a new printer profile starts with on its Printer parts page (the real API's DEFAULT_PARTS), none filled in,
// and whether each starts ticked "Add to name"
export const DEFAULT_PARTS = [["Toolhead", true], ["Hotend", true], ["Nozzle", true], ["Extruder", true], ["Gantry", true], ["XY motor", false]];
export const defaultParts = (nextId) =>
  DEFAULT_PARTS.map(([part, inName]) => ({ id: nextId(), part, make: null, model: null, installed_on: null, note: null, in_name: inName }));

// A printer's lifetime figures from its jobs, the way Moonraker's /server/history/totals gives them
export const jobTotals = (list) => ({
  total_jobs: list.length,
  total_time: list.reduce((s, j) => s + j.totalS, 0),
  total_print_time: list.reduce((s, j) => s + j.printS, 0),
  total_filament_used: list.reduce((s, j) => s + j.filamentMm, 0),
  longest_job: Math.max(0, ...list.map((j) => j.totalS)),
  longest_print: Math.max(0, ...list.map((j) => j.printS)),
});

export function buildFarm() {
  const rand = rng(1190);
  const pick = (list) => list[Math.floor(rand() * list.length)];

  // ------------------------------------------------------------------ printers
  const printers = [
    {
      id: 1, name: "VT 1190", kind: "Voron Trident (Klipper / Moonraker)", wired_ip: "10.0.6.21", wireless_ip: null,
      decommissioned: false, created_at: iso(NOW - 420 * DAY),
      moonraker: { reachable: true, klippy_state: "ready", version: "v0.9.3-mock", meterSensor: "powermeter", idleKwhPerDay: 0.55 },
      notes: "Nozzle: 0.4 hardened steel (swapped 2026-08).\nBed: textured PEI, re-leveled after moving to rack 2.\nKeep the door closed for ABS.",
      serviceHoursSince: 812, serviceHistory: [{ hoursAgoDays: 190, hours: 1512, note: "Belts replaced, rails cleaned and oiled" }],
      serviceNotes: "Gates 6mm belts (2× 1.8 m)\nSuper Lube on rails, check toolhead wiring loom.",
    },
    {
      id: 2, name: "V2 BOG", kind: "Voron 2.4 (Klipper / Moonraker)", wired_ip: "192.168.10.123", wireless_ip: null,
      decommissioned: false, created_at: iso(NOW - 600 * DAY),
      moonraker: { reachable: true, klippy_state: "ready", version: "v0.10.0-31-mock", meterSensor: "powermeter", idleKwhPerDay: 0.7 },
      notes: "",
      serviceHoursSince: 1533, serviceHistory: [],
      serviceNotes: "",
    },
    {
      id: 3, name: "MK4 Shelf", kind: "Prusa MK4 (Klipper)", wired_ip: null, wireless_ip: "10.0.6.40",
      decommissioned: false, created_at: iso(NOW - 200 * DAY),
      moonraker: { reachable: false, error: "Moonraker at http://10.0.6.40:7125 didn't answer in time. Is the printer on?", error_kind: "unreachable", meterSensor: null },
      notes: "Wi-Fi only, sits on the top shelf.",
      serviceHoursSince: 240, serviceHistory: [], serviceNotes: "",
    },
    {
      id: 5, name: "Core One", kind: "Prusa Core One (PrusaLink)", wired_ip: "10.0.6.45", wireless_ip: null,
      decommissioned: false, created_at: iso(NOW - 150 * DAY),
      moonraker: null,
      // reached through PrusaLink: no history of its own, so its prints are the ones Farmhand recorded
      prusalink: { reachable: true, firmware: "6.2.0", username: "maker", hasPassword: true, url: null },
      notes: "Enclosed. PETG and ASA live here.",
      serviceHoursSince: 610, serviceHistory: [], serviceNotes: "",
    },
    {
      id: 4, name: "Ender 3 (retired)", kind: "Creality Ender 3", wired_ip: "10.0.6.77", wireless_ip: null, // found again by a scan
      decommissioned: true, created_at: iso(NOW - 900 * DAY),
      moonraker: null,
      notes: "Retired 2025. Kept for its 3MF history.", serviceHoursSince: null, serviceHistory: [], serviceNotes: "",
    },
  ];

  for (const p of printers) {
    // notes revisions, as the real database counts them (0 = never had notes)
    p.notesRevision = p.notes ? 1 : 0;
    p.notesUpdatedAt = p.notes ? iso(NOW - 45 * DAY) : null;
    p.serviceNotesRevision = p.serviceNotes ? 1 : 0;
    p.serviceNotesUpdatedAt = p.serviceNotes ? iso(NOW - 20 * DAY) : null;
  }

  // ------------------------------------------------------------------ models (STL/OBJ/STEP)
  let versionId = 100;
  const model = (id, name, fileType, createdDaysAgo, thumbs, notes = "") => ({
    id, name, file_type: fileType, created_at: iso(NOW - createdDaysAgo * DAY),
    versions: thumbs.map((thumb, i) => ({
      id: ++versionId, version: i + 1, file_path: `/data/storage/source_models/${id}/v${i + 1}/${name}`,
      thumbnail_path: thumb, thumb, note: i === 0 ? null : "Thicker keyring loop", uploaded_at: iso(NOW - (createdDaysAgo - i * 9) * DAY),
    })).reverse(),
    notes, notes_revision: notes ? 1 : 0, notes_updated_at: notes ? iso(NOW - 30 * DAY) : null,
  });
  const models = [
    model(1, "MMMini_GreatWhiteShark_v01.stl", "STL", 300, ["stl-shark"], "From the MMMini collection. Prints without supports at 0.2 mm.\nSells best in grey PLA."),
    model(2, "MMMini_Frog_verticalEyes_v01.stl", "STL", 260, ["stl-frog-vertical"]),
    model(3, "MMMini_Frog_horizontalEyes_Keychain_v01.stl", "STL", 255, ["stl-frog-keychain", "stl-frog-keychain"]),
    model(4, "Calibration cube.stl", "STL", 400, [null], "20 mm cube for flow and dimension checks."),
    model(5, "Spool holder bracket.step", "STEP", 120, [null]),
    model(6, "Flexi-Starfish.stl", "STL", 20, [null]),
  ];

  // ------------------------------------------------------------------ 3MF files (bundles) and their versions
  const settingsBySlug = {
    "shark-vt1190": settingsFixture("shark-vt1190"),
    "shark-v2bog": settingsFixture("shark-v2bog"),
    "frog-vt1190": settingsFixture("frog-vt1190"),
    "starfish-orca": settingsFixture("starfish-orca"), // sliced in OrcaSlicer, so shown in its layout
  };
  const versionSettings = {}; // version id -> settings
  let bundleVersionId = 0;
  const bundle = (id, printerId, modelIds, slug, createdDaysAgo, files, extra = {}) => {
    const base = settingsBySlug[slug];
    const versions = files.map((f, i) => {
      const id = ++bundleVersionId;
      // later versions get a few real-looking changes, so Compare has something to show
      versionSettings[id] = { ...base, ...(f.changes || {}) };
      return {
        id, version: i + 1, filename: f.name, slicer_family: f.family || "prusaslicer",
        slicer_display_name: f.slicer || "PrusaSlicer 2.9.6",
        printer_profile_name: printers.find((p) => p.id === printerId).name,
        uploaded_at: iso(NOW - (createdDaysAgo - i * 21) * DAY),
        monument: i === 0, monument_note: i === 0 ? "Initial upload" : null,
        full_files_retained: true, thumbnail_path: slug, thumb: slug,
        // the newest version of each 3MF has its G-code, named after it
        gcode_name: i === files.length - 1 ? f.name.replace(/\.3mf$/i, ".gcode") : null,
      };
    });
    return {
      id, printer_id: printerId, created_at: iso(NOW - createdDaysAgo * DAY), source_model_ids: modelIds,
      versions: versions.reverse(), starred_version_id: null, notes: "", notes_revision: 0, notes_updated_at: null, ...extra,
    };
  };
  const bundles = [
    bundle(1, 1, [1], "shark-vt1190", 280, [{ name: "VT_1190_-_prusa_slicer_-_MMMini_GreatWhiteShark_v01.3mf", slicer: "PrusaSlicer 2.9.5-rc1" }]),
    bundle(2, 2, [1], "shark-v2bog", 250, [
      { name: "V2_BOG_-_Prusa_Slicer_-_MMMini_GreatWhiteShark_v01.3mf" },
      { name: "V2_BOG_-_Prusa_Slicer_-_MMMini_GreatWhiteShark_v02.3mf", changes: { layer_height: "0.24", perimeters: "3", infill_density: "12%" } },
    ]),
    bundle(3, 1, [2, 3], "frog-vt1190", 240, [
      { name: "VT_1190_-_prusa_slicer_-_MMMini_Frog.3mf" },
      { name: "VT_1190_-_prusa_slicer_-_MMMini_Frog_v2.3mf", changes: { first_layer_temperature: "220", temperature: "215", brim_width: "3" } },
      { name: "VT_1190_-_prusa_slicer_-_MMMini_Frog_v3.3mf", changes: { first_layer_temperature: "220", temperature: "212", brim_width: "0", fill_pattern: "gyroid" } },
    ], { notes: "Mixed plate: both frogs together.\nTextured sheet, glue stick for the keychain loops.", notes_revision: 2, notes_updated_at: iso(NOW - 12 * DAY) }),
  ];
  bundles.push(bundle(4, 2, [6], "starfish-orca", 18, [{ name: "V2_BOG_-_Orca_Slicer_-_Flexi-Starfish.3mf", slicer: "OrcaSlicer 2.4.2", family: "orcaslicer" }]));
  bundles[2].starred_version_id = bundles[2].versions.find((v) => v.version === 2).id; // v2 is the keeper

  // Printer profiles: each printer's printer presets in PrusaSlicer, found from its 3MFs' printer_settings_id as the real
  // API does, plus one more on the VT 1190 (a 0.4 brass nozzle) that the Frog's v3 was sliced with
  const subPrinters = [];
  const subPrinterFor = (printerId, name) => {
    let s = subPrinters.find((x) => x.printer_id === printerId && x.name === name);
    if (!s) subPrinters.push((s = { id: subPrinters.length + 1, printer_id: printerId, name }));
    return s;
  };
  for (const b of bundles) for (const v of b.versions) v.sub_printer_id = subPrinterFor(b.printer_id, versionSettings[v.id].printer_settings_id).id;
  const frogV3 = bundles[2].versions.find((v) => v.version === 3);
  const brass = subPrinterFor(1, "Trident_Allyson_DragonBurner_0.4_brass");
  frogV3.sub_printer_id = brass.id;
  versionSettings[frogV3.id] = { ...versionSettings[frogV3.id], printer_settings_id: brass.name, nozzle_diameter: "0.4" };
  // Their Printer parts pages: every printer profile starts with the default parts (as the real API does), and a few of
  // the VT 1190's are filled in
  let partId = 0;
  for (const s of subPrinters) s.parts = defaultParts(() => ++partId);
  const fill = (s, part, fields) => Object.assign(s.parts.find((p) => p.part === part), fields);
  const rapido = subPrinters.find((s) => s.printer_id === 1 && s.name.includes("Rapido"));
  fill(rapido, "Toolhead", { make: "Voron Design", model: "Stealthburner", installed_on: "2025-11-20" });
  fill(rapido, "Hotend", { make: "Phaetus", model: "Rapido UHF", installed_on: "2026-03-02", note: "Replaced the Dragon after the heat-creep clogs." });
  fill(rapido, "Nozzle", { make: "Phaetus", model: "0.5 WC", installed_on: "2026-03-02", note: "Tungsten carbide." });
  fill(rapido, "Extruder", { make: "JaredC01", model: "Galileo 2", installed_on: "2025-11-20" });
  fill(rapido, "XY motor", { make: "LDO", model: "42STH48-2504AC" });
  fill(brass, "Nozzle", { make: "E3D", model: "V6 0.4 mm brass", note: "Kept for fine detail prints." });

  // ------------------------------------------------------------------ print history, totals and energy
  const fileNames = {
    1: ["VT_1190_-_prusa_slicer_-_MMMini_GreatWhiteShark_v01.gcode", "VT_1190_-_prusa_slicer_-_MMMini_Frog_v2.gcode", "calibration_cube.gcode", "VT_1190_benchy.gcode", "spool_holder_bracket.gcode"],
    2: ["V2_BOG_-_Prusa_Slicer_-_MMMini_GreatWhiteShark_v02.gcode", "V2 BOG - Prusa Slicer - MMMini_GreatWhiteShark_v02-V2_BOG_Rapido_Ace_0.5_WC-Inland_PLA.gcode","V2 BOG - Prusa Slicer - MMMini_LeoGecko v01.gcode", "V2_BOG_bed_mesh_test.gcode", "V2_BOG_voron_cube.gcode"],
    3: ["MK4_shelf_keychains_x12.gcode", "MK4_cable_clips.gcode"],
    5: ["COREONE_MMMini_GreatWhiteShark_PETG.bgcode", "COREONE_Frog_keychain_x8.bgcode", "COREONE_spool_holder_bracket_ASA.bgcode"],
  };
  // The filament settings Farmhand has read from the end of each G-code on the Klipper printers ({printer id: {file:
  // [price per kg, density, diameter]}}). The ones left out were gone from the printer, so their prints fall back to
  // the 3MF (or have no cost)
  const gcodeFilament = {
    1: { "VT_1190_benchy.gcode": [22.5, 1.24, 1.75], "VT_1190_-_prusa_slicer_-_MMMini_Frog_v2.gcode": [16.99, 1.23, 1.75] },
    2: {
      "V2 BOG - Prusa Slicer - MMMini_LeoGecko v01.gcode": [16.99, 1.23, 1.75], "V2_BOG_voron_cube.gcode": [27, 1.27, 1.75],
      "V2 BOG - Prusa Slicer - MMMini_GreatWhiteShark_v02-V2_BOG_Rapido_Ace_0.5_WC-Inland_PLA.gcode": [16.99, 1.23, 1.75],
    },
  };
  const statusOf = () => {
    const r = rand();
    return r < 0.84 ? "completed" : r < 0.93 ? "cancelled" : r < 0.98 ? "error" : "klippy_shutdown";
  };
  const jobs = {}; // printer id -> jobs, oldest first
  const meterReadings = {}; // printer id -> [[unix, kWh]]
  for (const p of printers) {
    if (!fileNames[p.id]) continue;
    const list = [];
    const count = p.id === 2 ? 240 : p.id === 1 ? 180 : p.id === 5 ? 70 : 60;
    const span = (p.id === 3 ? 200 : p.id === 5 ? 150 : 420) * DAY;
    let t = NOW - span;
    for (let i = 0; i < count; i++) {
      t += (span / count) * (0.4 + rand() * 1.2);
      if (t > NOW - 3 * HOUR) break;
      const drawn = statusOf();
      const status = p.prusalink && drawn === "klippy_shutdown" ? "unknown" : drawn; // PrusaLink has no Klipper to shut down
      const planned = (0.6 + rand() * 9) * HOUR;
      const printS = status === "completed" ? planned : planned * (0.05 + rand() * 0.8);
      const watts = 200 + rand() * 90;
      list.push({
        job_id: (0x3000 + p.id * 0x400 + i).toString(16).toUpperCase().padStart(6, "0"),
        filename: pick(fileNames[p.id]), status, start: Math.floor(t), printS, totalS: printS + rand() * 900,
        filamentMm: p.prusalink ? 0 : printS / HOUR * (1800 + rand() * 2600), kwh: p.moonraker?.meterSensor ? (printS / HOUR) * (watts / 1000) : null,
        avgW: p.moonraker?.meterSensor ? watts : null, maxW: p.moonraker?.meterSensor ? watts + 300 + rand() * 120 : null,
        estimated: planned,
      });
    }
    // the newest job on the first printer is still printing
    if (p.id === 1) {
      list.push({ job_id: "0035FF", filename: "VT_1190_-_prusa_slicer_-_MMMini_Frog_v2.gcode", status: "in_progress", start: NOW - 2 * HOUR, printS: 2 * HOUR, totalS: 2 * HOUR, filamentMm: 6100, kwh: 0.47, avgW: 236, maxW: 610, estimated: 5 * HOUR });
    }
    // ...and on the Core One, recorded by Farmhand as it runs
    if (p.id === 5) {
      list.push({ job_id: "41@20261025T090000", filename: "COREONE_MMMini_GreatWhiteShark_PETG.bgcode", status: "in_progress", start: NOW - 1.5 * HOUR, printS: 1.5 * HOUR, totalS: 1.5 * HOUR, filamentMm: 0, kwh: null, avgW: null, maxW: null, estimated: 4 * HOUR });
    }
    jobs[p.id] = list;
    // Farmhand has read the meter every day for the last ~4 months (whole printer: prints plus idle)
    if (p.moonraker?.meterSensor) {
      const readings = [];
      let meter = 1500 + rand() * 600;
      const firstDay = NOW - 118 * DAY;
      for (let d = firstDay; d <= NOW; d += DAY) {
        const printed = list.filter((j) => j.kwh && j.start >= d - DAY && j.start < d).reduce((s, j) => s + j.kwh, 0);
        meter += printed + p.moonraker.idleKwhPerDay * (0.8 + rand() * 0.4);
        readings.push([d, Math.round(meter * 1000) / 1000]);
      }
      meterReadings[p.id] = readings;
    }
  }

  // ------------------------------------------------------------------ maintenance kept on the printers (Mainsail's format)
  const totalsFor = (printerId) => jobTotals(jobs[printerId] || []);
  const reminder = (type, parts = {}) => ({
    type,
    filament: { bool: !!parts.filament, value: parts.filament ?? null },
    printtime: { bool: !!parts.printtime, value: parts.printtime ?? null },
    date: { bool: !!parts.date, value: parts.date ?? null },
  });
  const entry = (printerId, name, note, rem, { startedDaysAgo, printedHoursAgo = 0, filamentMAgo = 0, doneDaysAgo = null, performNote = null }) => {
    const t = totalsFor(printerId);
    return {
      name, note, perform_note: performNote,
      start_time: NOW - startedDaysAgo * DAY, end_time: doneDaysAgo == null ? null : NOW - doneDaysAgo * DAY,
      start_filament: t.total_filament_used - filamentMAgo * 1000, end_filament: doneDaysAgo == null ? null : t.total_filament_used,
      start_printtime: t.total_print_time - printedHoursAgo * HOUR, end_printtime: doneDaysAgo == null ? null : t.total_print_time,
      last_entry: null, reminder: rem,
    };
  };
  const maintenance = {
    1: {
      "a1f0c2d4-0001": entry(1, "Lube Z rails", "Super Lube, all three Z rails", reminder("repeat", { printtime: 200 }), { startedDaysAgo: 40, printedHoursAgo: 120 }),
      "a1f0c2d4-0002": entry(1, "Clean the bed", "IPA, then dish soap once a month", reminder("repeat", { date: 30 }), { startedDaysAgo: 34 }),
      "a1f0c2d4-0003": entry(1, "Replaced hotend fan", "", reminder(null), { startedDaysAgo: 80, doneDaysAgo: 80, performNote: "Noctua 40mm, quieter" }),
    },
    2: {
      "b2e1d3c5-0001": entry(2, "started triceratops at 3909h 29m 41s", "Started at total print time = 3909h 29m 41s", reminder(null), { startedDaysAgo: 210 }),
      "b2e1d3c5-0002": entry(2, "RMG renovation at 3533h 59m 5s", "redid the gantry.", reminder(null), { startedDaysAgo: 260 }),
      "b2e1d3c5-0003": entry(2, "Check belt tension", "", reminder("repeat", { filament: 400, printtime: 150 }), { startedDaysAgo: 25, printedHoursAgo: 90, filamentMAgo: 410 }),
      "b2e1d3c5-0004": entry(2, "Need to replace gantry", "Seeing metal flakes", reminder("one-time", { date: 14 }), { startedDaysAgo: 20 }),
    },
    // kept in Farmhand: PrusaLink has nowhere to keep them (and no filament figures to count)
    5: {
      "c3f2e4d6-0001": entry(5, "Clean the nozzle wiper", "", reminder("repeat", { printtime: 100 }), { startedDaysAgo: 18, printedHoursAgo: 104 }),
      "c3f2e4d6-0002": entry(5, "Check the enclosure filter", "Replace when it smells", reminder("repeat", { date: 60 }), { startedDaysAgo: 22 }),
    },
  };

  // ------------------------------------------------------------------ settings, storage, shares
  const config = {
    appearance: { scheme: "farmhand", contrast: 0, font: "archivo", size: "default", file_name_color: "auto" },
    preferences: {
      model_sort: { key: "name", dir: "asc" }, monitor_order: [], monitor_max_zoom: 4, farm_cost_order: [], energy_price_per_kwh: 0.17,
      // the average cost was 0.15 until September, then 0.17; March was given its own price
      energy_price_history: [{ from: "2025-11", price: 0.15 }, { from: "2026-09", price: 0.17 }],
      energy_price_months: { "2026-03": 0.142 },
      tool_links: [ // the server's defaults (config_store.DEFAULT_TOOL_LINKS)
        { name: "CANBus guide (Esoterical)", url: "https://canbus.esoterical.online/" },
        { name: "USB guide (Esoterical)", url: "https://usb.esoterical.online/" },
        { name: "A better print_start macro", url: "https://abetterprintstartmacro.com/" },
        { name: "Klipper TMC Autotune", url: "https://github.com/andrewmcgr/klipper_tmc_autotune" },
        { name: "Klippain Shake&Tune", url: "https://github.com/Frix-x/klippain-shaketune" },
        { name: "Klippy Detective", url: "https://klippydetective.com/" },
        { name: "Energy usage monitoring (Voron mods)", url: "https://mjonuschat.github.io/voron-mods/docs/guides/energy-usage-monitoring-tracking/" },
        { name: "Kalico documentation", url: "https://docs.kalico.gg/" },
        { name: "KIAUH (Klipper Installation And Update Helper)", url: "https://github.com/dw-0/kiauh" },
        { name: "Klipper documentation", url: "https://www.klipper3d.org/" },
        { name: "KlipperScreen documentation", url: "https://klipperscreen.readthedocs.io/en/latest/" },
        { name: "Mainsail documentation", url: "https://docs.mainsail.xyz/" },
        { name: "Moonraker Timelapse", url: "https://github.com/mainsail-crew/moonraker-timelapse" },
      ],
    },
  };
  const shares = [
    {
      id: 1, name: "farm-nas", protocol: "smb", server: "192.168.10.5", share: "farmhand", username: "farm", domain: null, version: "3.0",
      has_password: true, address: "smb://192.168.10.5/farmhand", mount_point: "/data/nas/farm-nas", mounted: true, error: null, error_kind: null, files_here: 6,
    },
  ];

  // ------------------------------------------------------------------ projects: a name, and their CAD files
  // (each version's `thumb` is the stand-in picture the mockup shows as its preview; null = none could be made)
  const cadVersion = (version, filename, size_bytes, note, daysAgo, thumb) => ({
    version, filename, size_bytes, note, uploaded_at: iso(NOW - daysAgo * DAY), thumb,
  });
  const projects = [
    {
      id: 1, name: "Aquarium shop order", created_at: iso(NOW - 6 * DAY),
      cad_files: [
        {
          id: 1, created_at: iso(NOW - 6 * DAY),
          versions: [
            cadVersion(3, "Shop display stand ver 3.f3d", 2_412_000, "Wider base, slots for 24 sharks", 1, "stl-shark"),
            cadVersion(2, "Shop display stand ver 2.f3d", 2_198_000, "Rounded edges", 4, "stl-shark"),
            cadVersion(1, "Shop display stand ver 1.f3d", 1_904_000, null, 6, "stl-shark"),
          ],
        },
        { id: 2, created_at: iso(NOW - 3 * DAY), versions: [cadVersion(1, "Starfish tag ver 1.step", 318_000, null, 3, "stl-frog-vertical")] },
        { id: 3, created_at: iso(NOW - 2 * DAY), versions: [cadVersion(1, "Pump housing ver 1.SLDPRT", 1_120_000, "From the supplier", 2, null)] },
      ],
      // its STLs: two models from Models, and one of its own (not in Models)
      source_model_ids: [1, 6],
      stl_files: [
        {
          id: 4, created_at: iso(NOW - 2 * DAY),
          versions: [
            cadVersion(2, "Display stand clip ver 2.stl", 412_000, "Thicker hook", 1, "stl-frog-vertical"),
            cadVersion(1, "Display stand clip ver 1.stl", 398_000, null, 2, "stl-frog-vertical"),
          ],
        },
      ],
    },
    { id: 2, name: "Frog keychains for the fair", created_at: iso(NOW - 20 * DAY), cad_files: [], stl_files: [], source_model_ids: [2, 3] },
  ];

  return {
    now: NOW, printers, models, bundles, versionSettings, subPrinters, jobs, meterReadings, maintenance, config, shares, gcodeFilament, projects,
    // printer id -> { last_sync_at, last_sync_error }: the two online printers synced recently, the MK4 is off
    connections: {
      1: { last_sync_at: iso(NOW - 40 * 60), last_sync_error: null },
      2: { last_sync_at: iso(NOW - 25 * 60), last_sync_error: null },
      3: { last_sync_at: iso(NOW - 3 * DAY), last_sync_error: printers[2].moonraker.error },
      5: { last_sync_at: iso(NOW - 40), last_sync_error: null },
    },
    settingsFolder: "/data/nas/farm-nas/farmhand-settings",
    storage: { stl: "/data/nas/farm-nas/models", threemf: "/data/nas/farm-nas/3mf", project: "/data/nas/farm-nas/projects" },
    nextIds: { printer: 10, model: 10, bundleVersion: 50, job: 1, share: 5, subPrinter: 20, part: 100, project: 10, cad: 10 },
  };
}
