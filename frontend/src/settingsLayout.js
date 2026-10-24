// Settings grouping/formatting helpers, extracted unchanged from the mockup.

export const CATEGORY_RULES = [
  { test: (k) => k.includes("gcode"), category: "Custom G-code" },
  { test: (k) => k.includes("speed"), category: "Speed" },
  { test: (k) => k.includes("acceleration") || k.includes("jerk") || k.includes("cruise_ratio"), category: "Kinematics" },
  { test: (k) => k.includes("retract") || k.includes("ramming") || k.includes("wipe"), category: "Retraction" },
  { test: (k) => k.includes("temperature") || k.includes("chamber"), category: "Temperature" },
  { test: (k) => k.includes("cooling") || k.includes("fan"), category: "Cooling" },
  { test: (k) => k.includes("support"), category: "Support Material" },
  { test: (k) => k.startsWith("fill") || k.includes("infill"), category: "Infill" },
  { test: (k) => k.includes("skirt") || k.includes("brim"), category: "Skirt & Brim" },
  { test: (k) => k.includes("perimeter") || k.includes("layer") || k.includes("seam") || k.includes("overhang"), category: "Layers & Perimeters" },
  { test: (k) => k.startsWith("filament"), category: "Filament" },
  { test: (k) => k.startsWith("printer") || k.startsWith("machine") || k.includes("bed") || k.includes("nozzle") || k.includes("extruder"), category: "Printer" },
];
export const categorizeKey = (key) => (CATEGORY_RULES.find((r) => r.test(key)) || { category: "Other Settings" }).category;

export const humanizeLabel = (key) =>
  key.split("_").join(" ").replace(/\b\w/g, (ch) => ch.toUpperCase());

export function formatVal(raw) {
  if (raw === undefined || raw === null || raw === "") return "—";
  const s = String(raw);
  return s.length > 70 ? s.slice(0, 70) + "…" : s;
}

// ---------------------------------------------------------------------------
// PrusaSlicer 2.9–style classification for the single-file "Display Settings"
// viewer — mirrors the three top-level tabs (Print / Filament / Printer
// Settings) and their left-hand sub-page navigation, so a bundle's settings
// read the way they would inside PrusaSlicer itself. Best-effort mapping by
// key pattern (PrusaSlicer's own config has no tab metadata in the file) —
// order matters, first match wins, checked top to bottom.
// ---------------------------------------------------------------------------
export const PRUSA_SECTIONS = {
  "Print Settings": [
    "Layers and perimeters", "Infill", "Skirt and brim", "Support material",
    "Speed", "Multiple Extruders", "Advanced", "Output options", "Notes", "Dependencies",
  ],
  "Filament Settings": ["Filament", "Cooling", "Advanced", "Multimaterial", "Custom G-code", "Notes", "Dependencies"],
  "Printer Settings": ["General", "Extruder 1", "Custom G-code", "Notes", "Firmware"],
};

export const PRUSA_RULES = [
  // Custom G-code — split by which profile owns it
  { test: (k) => k === "start_filament_gcode" || k === "end_filament_gcode", tab: "Filament Settings", section: "Custom G-code" },
  { test: (k) => ["start_gcode", "end_gcode", "before_layer_gcode", "layer_gcode", "toolchange_gcode", "between_objects_gcode", "pause_print_gcode", "template_custom_gcode", "color_change_gcode"].includes(k), tab: "Printer Settings", section: "Custom G-code" },
  // Notes
  { test: (k) => k === "printer_notes", tab: "Printer Settings", section: "Notes" },
  { test: (k) => k === "notes", tab: "Print Settings", section: "Notes" },
  // Machine limits / firmware (checked before the generic speed/acceleration rule below)
  { test: (k) => k.startsWith("machine_") || k === "silent_mode", tab: "Printer Settings", section: "Firmware" },
  // Extruder (retraction, per-extruder geometry) — Printer Settings in PrusaSlicer, not Print
  { test: (k) => k.includes("retract") || k === "wipe" || ["extruder_offset", "extruder_colour", "nozzle_diameter", "min_layer_height", "max_layer_height", "extra_loading_move"].includes(k), tab: "Printer Settings", section: "Extruder 1" },
  // Printer > General
  { test: (k) => ["bed_shape", "bed_custom_model", "bed_custom_texture", "max_print_height", "z_offset", "gcode_flavor", "single_extruder_multi_material", "complete_objects", "duplicate_distance", "extruders_count"].includes(k), tab: "Printer Settings", section: "General" },
  // Filament — temperatures live on the Filament page, not Printer, in PrusaSlicer
  { test: (k) => k.startsWith("filament_") && (k.includes("ramming") || k.includes("cooling_tube") || k.includes("parking_pos")), tab: "Filament Settings", section: "Multimaterial" },
  { test: (k) => ["cooling_tube_length", "cooling_tube_retraction", "parking_pos_retraction"].includes(k), tab: "Filament Settings", section: "Multimaterial" },
  { test: (k) => k.includes("cooling") || k.includes("fan") || k === "slowdown_below_layer_time", tab: "Filament Settings", section: "Cooling" },
  { test: (k) => ["temperature", "first_layer_temperature", "bed_temperature", "first_layer_bed_temperature", "bed_temperature_extruder", "chamber_temperature", "chamber_minimal_temperature"].includes(k), tab: "Filament Settings", section: "Filament" },
  { test: (k) => k === "extrusion_multiplier", tab: "Filament Settings", section: "Advanced" },
  { test: (k) => k.startsWith("filament_"), tab: "Filament Settings", section: "Filament" },
  // Print > Skirt & brim / Support
  { test: (k) => k.includes("skirt") || k.includes("brim") || k === "draft_shield", tab: "Print Settings", section: "Skirt and brim" },
  { test: (k) => k.includes("support") || k.includes("raft"), tab: "Print Settings", section: "Support material" },
  // Print > Infill
  { test: (k) => k.startsWith("fill") || k.includes("infill"), tab: "Print Settings", section: "Infill" },
  // Print > Multiple Extruders
  { test: (k) => k.includes("wipe_tower") || k === "ooze_prevention" || k === "standby_temperature_delta" || k.includes("interlocking"), tab: "Print Settings", section: "Multiple Extruders" },
  // Print > Speed (process-level speed/acceleration/jerk, after machine_* already routed away)
  { test: (k) => k.includes("speed") || k.includes("acceleration") || k.includes("jerk") || k.includes("cruise_ratio"), tab: "Print Settings", section: "Speed" },
  // Print > Layers and perimeters
  { test: (k) => k.includes("perimeter") || k.includes("layer") || k === "seam_position" || k.includes("overhang") || k.includes("fuzzy_skin") || k === "spiral_vase" || k.includes("arc_fitting"), tab: "Print Settings", section: "Layers and perimeters" },
  // Print > Advanced (extrusion widths, resolution, compensation)
  { test: (k) => k.includes("extrusion_width") || k.includes("avoid_crossing") || k.includes("compensation") || ["resolution", "gcode_resolution", "slice_closing_radius", "threads", "clip_multipart_objects", "xy_size_compensation"].includes(k), tab: "Print Settings", section: "Advanced" },
  // Print > Output options
  { test: (k) => ["output_filename_format", "post_process", "gcode_comments", "label_objects", "thumbnails", "binary_gcode", "gcode_substitutions"].includes(k), tab: "Print Settings", section: "Output options" },
  // Dependencies
  { test: (k) => k === "inherits" || k.startsWith("compatible_printers") || k.endsWith("_settings_id"), tab: "Print Settings", section: "Dependencies" },
];

export function classifyPrusa(key) {
  const rule = PRUSA_RULES.find((r) => r.test(key));
  if (rule) return rule;
  if (key.startsWith("filament")) return { tab: "Filament Settings", section: "Advanced" };
  if (key.startsWith("printer") || key.startsWith("machine")) return { tab: "Printer Settings", section: "General" };
  return { tab: "Print Settings", section: "Advanced" };
}
