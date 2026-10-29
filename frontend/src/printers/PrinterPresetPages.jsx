import { useEffect, useMemo, useState } from "react";
import { ChevronDown, CircleDot, FileCode, Gauge, Link2, Printer, Puzzle, StickyNote } from "lucide-react";
import { c, fs, mono, ui } from "../theme.js";
import { errorText, fetchVersionSettings } from "../api.js";
import { classifyPrusa } from "../settingsLayout.js";
import { monoText, uiText } from "../styles.js";

// A printer preset (a sub printer) laid out as PrusaSlicer's (and BOSS edition's) Printer Settings tab: the same
// pages down the left, the same titled groups on each page, the same labels and units, and one Extruder page per
// extruder. Read from a 3MF sliced with it, so it's read-only: the fields are drawn, never typed in.

// Each row: [key, label, kind or unit]. Kinds: "bool" (a tick box), "enum" (a drop-down), "color", "gcode" (a text
// box across the page), "bed". Anything else is the unit shown after the field.
const GENERAL = [
  {
    title: "Size and coordinates",
    rows: [
      ["bed_shape", "Bed shape", "bed"], ["bed_custom_texture", "Bed texture"], ["bed_custom_model", "Bed model"],
      ["max_print_height", "Max print height", "mm"], ["z_offset", "Z offset", "mm"],
    ],
  },
  { title: "Capabilities", rows: [["@extruders", "Extruders"], ["single_extruder_multi_material", "Single Extruder Multi Material", "bool"]] },
  {
    title: "Firmware",
    rows: [
      ["gcode_flavor", "G-code flavor", "enum"], ["thumbnails", "G-code thumbnails"], ["binary_gcode", "Supports binary G-code", "bool"],
    ],
  },
  {
    title: "Advanced",
    rows: [
      ["use_relative_e_distances", "Use relative E distances", "bool"], ["use_firmware_retraction", "Use firmware retraction", "bool"],
      ["use_volumetric_e", "Use volumetric E", "bool"], ["variable_layer_height", "Enable variable layer height feature", "bool"],
      ["remaining_times", "Supports remaining times", "bool"],
    ],
  },
  {
    title: "Single extruder multimaterial parameters",
    rows: [
      ["cooling_tube_retraction", "Cooling tube position", "mm"], ["cooling_tube_length", "Cooling tube length", "mm"],
      ["parking_pos_retraction", "Filament parking position", "mm"], ["extra_loading_move", "Extra loading distance", "mm"],
      ["multimaterial_purging", "Purging volume", "mm³"], ["high_current_on_filament_swap", "High extruder current on filament swap", "bool"],
    ],
  },
];
// Printer-looking settings that PrusaSlicer keeps on its Print or Filament tabs, so not on these pages
const NOT_PRINTER = (k) => k.startsWith("filament_") || [
  "complete_objects", "duplicate_distance", "extruder_clearance_height", "extruder_clearance_radius", "only_retract_when_crossing_perimeters",
].includes(k);
const CUSTOM_GCODE = [
  { title: "Start G-code", rows: [["start_gcode", "", "gcode"], ["autoemit_temperature_commands", "Emit temperature commands automatically", "bool"]] },
  { title: "End G-code", rows: [["end_gcode", "", "gcode"]] },
  { title: "Before layer change G-code", rows: [["before_layer_gcode", "", "gcode"]] },
  { title: "After layer change G-code", rows: [["layer_gcode", "", "gcode"]] },
  { title: "Tool change G-code", rows: [["toolchange_gcode", "", "gcode"], ["autoemit_toolchange_commands", "Emit tool change commands automatically", "bool"]] },
  { title: "Between objects G-code (for sequential printing)", rows: [["between_objects_gcode", "", "gcode"]] },
  { title: "Color Change G-code", rows: [["color_change_gcode", "", "gcode"]] },
  { title: "Pause Print G-code", rows: [["pause_print_gcode", "", "gcode"]] },
  { title: "Template Custom G-code", rows: [["template_custom_gcode", "", "gcode"]] },
];
// Machine limits hold two values each, Normal and Stealth (silent) mode
const MACHINE_LIMITS = [
  { title: "General", rows: [["machine_limits_usage", "How to apply limits", "enum"], ["silent_mode", "Supports stealth mode", "bool"]] },
  {
    title: "Maximum feedrates", limits: true,
    rows: [["machine_max_feedrate_x", "Maximum feedrate X", "mm/s"], ["machine_max_feedrate_y", "Maximum feedrate Y", "mm/s"], ["machine_max_feedrate_z", "Maximum feedrate Z", "mm/s"], ["machine_max_feedrate_e", "Maximum feedrate E", "mm/s"]],
  },
  {
    title: "Maximum accelerations", limits: true,
    rows: [
      ["machine_max_acceleration_x", "Maximum acceleration X", "mm/s²"], ["machine_max_acceleration_y", "Maximum acceleration Y", "mm/s²"],
      ["machine_max_acceleration_z", "Maximum acceleration Z", "mm/s²"], ["machine_max_acceleration_e", "Maximum acceleration E", "mm/s²"],
      ["machine_max_acceleration_extruding", "Maximum acceleration when extruding", "mm/s²"],
      ["machine_max_acceleration_retracting", "Maximum acceleration when retracting", "mm/s²"],
      ["machine_max_acceleration_travel", "Maximum acceleration for travel moves", "mm/s²"],
    ],
  },
  {
    title: "Jerk limits", limits: true,
    rows: [
      ["machine_max_jerk_x", "Maximum jerk X", "mm/s"], ["machine_max_jerk_y", "Maximum jerk Y", "mm/s"], ["machine_max_jerk_z", "Maximum jerk Z", "mm/s"],
      ["machine_max_jerk_e", "Maximum jerk E", "mm/s"], ["machine_max_junction_deviation", "Maximum Junction Deviation", "mm"],
    ],
  },
  {
    title: "Minimum feedrates", limits: true,
    rows: [["machine_min_extruding_rate", "Minimum feedrate when extruding", "mm/s"], ["machine_min_travel_rate", "Minimum travel feedrate", "mm/s"]],
  },
];
// One page per extruder: these keys hold a value per extruder (extruder_colour separated by ";", the rest by ",")
const EXTRUDER = [
  { title: "Size", rows: [["nozzle_diameter", "Nozzle diameter", "mm"], ["nozzle_high_flow", "High flow nozzle", "bool"]] },
  { title: "Preview", rows: [["extruder_colour", "Extruder Color", "color"]] },
  { title: "Layer height limits", rows: [["min_layer_height", "Min", "mm"], ["max_layer_height", "Max", "mm"]] },
  { title: "Position (for multi-extruder printers)", rows: [["extruder_offset", "Extruder offset", "mm"]] },
  {
    title: "Travel lift",
    rows: [
      ["retract_lift", "Lift height", "mm"], ["travel_ramping_lift", "Ramping lift", "bool"], ["travel_max_lift", "Maximum ramping lift", "mm"],
      ["travel_slope", "Ramping slope angle", "°"], ["travel_lift_before_obstacle", "Steeper ramp before obstacles", "bool"],
    ],
  },
  { title: "Only lift", rows: [["retract_lift_enforce", "On surfaces", "enum"], ["retract_lift_above", "Above Z", "mm"], ["retract_lift_below", "Below Z", "mm"]] },
  {
    title: "Retraction",
    rows: [
      ["retract_length", "Length", "mm"], ["retract_speed", "Retraction Speed", "mm/s"], ["deretract_speed", "Deretraction Speed", "mm/s"],
      ["retract_restart_extra", "Extra length on restart", "mm"], ["retract_before_travel", "Minimum travel after retraction", "mm"],
      ["retract_layer_change", "Retract on layer change", "bool"], ["wipe", "Wipe while retracting", "bool"],
      ["retract_before_wipe", "Retract amount before wipe", "%"],
    ],
  },
  {
    title: "Retraction when tool is disabled (advanced settings for multi-extruder setups)",
    rows: [["retract_length_toolchange", "Length", "mm"], ["retract_restart_extra_toolchange", "Extra length on restart", "mm"]],
  },
];
const PER_EXTRUDER = new Set(EXTRUDER.flatMap((g) => g.rows.map((r) => r[0])));
const NOTES = [{ title: "Notes", rows: [["printer_notes", "", "gcode"]] }];
const DEPENDENCIES = [
  {
    title: "Profile dependencies",
    rows: [["printer_settings_id", "Current preset"], ["@parent", "Parent preset"], ["printer_vendor", "Vendor"], ["printer_model", "Printer model"], ["printer_variant", "Variant"], ["printer_technology", "Printer technology"]],
  },
];

// How PrusaSlicer names the choices in its drop-downs
const CHOICES = {
  gcode_flavor: {
    reprap: "RepRap/Sprinter", reprapfirmware: "RepRapFirmware", repetier: "Repetier", teacup: "Teacup", makerware: "MakerWare (MakerBot)",
    marlin: "Marlin (legacy)", marlin2: "Marlin 2", klipper: "Klipper", sailfish: "Sailfish (MakerBot)", mach3: "Mach3/LinuxCNC",
    machinekit: "Machinekit", smoothie: "Smoothie", "no-extrusion": "No extrusion",
  },
  machine_limits_usage: { emit_to_gcode: "Emit to G-code", time_estimate_only: "Use for time estimate", ignore: "Ignore" },
  retract_lift_enforce: { all_surfaces: "All surfaces", first_layer: "First layer only", bottom_solid: "Bottom solid surfaces", top_solid: "Top solid surfaces", bottom_top_solid: "Bottom and top surfaces" },
};

// Text settings are saved with \n, \\ and \" escapes in the 3MF
const unescape = (v) => String(v).replace(/\\(.)/g, (_, ch) => (ch === "n" ? "\n" : ch === "t" ? "\t" : ch));
const isOn = (v) => v === "1" || v === 1 || v === true;
const pick = (key, raw, index) => {
  if (raw == null || index == null || !PER_EXTRUDER.has(key)) return raw;
  const parts = String(raw).split(key === "extruder_colour" ? ";" : ",");
  return parts[index] ?? parts[0];
};
const bedSummary = (raw) => {
  const pts = String(raw || "").split(",").map((p) => p.split("x").map(Number)).filter((p) => p.length === 2 && p.every(Number.isFinite));
  if (pts.length < 3) return raw || "";
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const w = Math.max(...xs) - Math.min(...xs), h = Math.max(...ys) - Math.min(...ys);
  return pts.length === 4 ? `Rectangular, ${w} × ${h} mm, origin ${-Math.min(...xs)}, ${-Math.min(...ys)}` : `Custom shape, ${pts.length} points, ${w} × ${h} mm`;
};

// ---- the fields, drawn the way PrusaSlicer draws them but never editable ----
const boxStyle = (extra) => ({
  ...mono, fontSize: fs(12), color: c.textPrimary, background: c.panelAlt, border: `1px solid ${c.border}`, borderRadius: 3,
  padding: "3px 8px", minHeight: 24, boxSizing: "border-box", display: "inline-flex", alignItems: "center", gap: 6, ...extra,
});
const missing = <span style={{ color: c.textFaint }}>—</span>;

function Field({ kind, value, choices }) {
  if (kind === "bool") {
    return <input type="checkbox" checked={isOn(value)} readOnly disabled aria-label={isOn(value) ? "on" : "off"} style={{ margin: 0, width: 15, height: 15, accentColor: c.amber }} />;
  }
  if (value == null || value === "") return <span style={boxStyle({ minWidth: 90 })}>{missing}</span>;
  if (kind === "enum") {
    return (
      <span style={boxStyle({ minWidth: 170, justifyContent: "space-between" })}>
        {choices?.[value] || value}
        <ChevronDown size={12} color={c.textFaint} />
      </span>
    );
  }
  if (kind === "color") {
    return (
      <span style={boxStyle()}>
        <span style={{ width: 28, height: 14, borderRadius: 2, background: value, border: `1px solid ${c.borderStrong}` }} />
        {value}
      </span>
    );
  }
  if (kind === "bed") return <span style={boxStyle({ fontFamily: "inherit", ...ui })}>{bedSummary(value)}</span>;
  return <span style={boxStyle({ minWidth: 90, maxWidth: "100%", overflowWrap: "anywhere" })}>{unescape(value)}</span>;
}

function Row({ label, kind, unit, value, limits, choices }) {
  if (kind === "gcode") {
    const text = value == null ? "" : unescape(value);
    return (
      <textarea
        readOnly
        value={text}
        rows={Math.min(14, Math.max(3, text.split("\n").length))}
        aria-label={label || "G-code"}
        style={{ ...boxStyle({ display: "block", width: "100%", resize: "vertical", whiteSpace: "pre", overflowX: "auto", lineHeight: 1.5, padding: "6px 8px" }) }}
      />
    );
  }
  const values = limits && value != null ? String(value).split(",") : [value];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(140px, 280px) 1fr", gap: 12, alignItems: "center", padding: "3px 0" }}>
      <div style={uiText(12, c.textMuted, { textAlign: "right" })}>{label}:</div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", minWidth: 0 }}>
        {values.map((v, i) => <Field key={i} kind={kind} value={v} choices={choices} />)}
        {unit && <span style={uiText(12, c.textFaint)}>{unit}</span>}
      </div>
    </div>
  );
}

function Group({ group, value }) {
  return (
    <fieldset style={{ border: `1px solid ${c.border}`, borderRadius: 4, padding: "6px 14px 10px", margin: 0, minWidth: 0 }}>
      <legend style={uiText(13, c.heading, { fontWeight: 600, padding: "0 6px" })}>{group.title}</legend>
      {group.limits && (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(140px, 280px) 1fr", gap: 12 }}>
          <span />
          <span style={uiText(11, c.textFaint, { display: "flex", gap: 8 })}>
            <span style={{ minWidth: 90 }}>Normal</span>
            <span>Stealth</span>
          </span>
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {group.rows.map(([key, label, kindOrUnit]) => {
          const kinds = ["bool", "enum", "color", "gcode", "bed"];
          const kind = kinds.includes(kindOrUnit) ? kindOrUnit : null;
          return <Row key={key} label={label} kind={kind} unit={kind ? null : kindOrUnit} value={value(key)} limits={group.limits} choices={CHOICES[key]} />;
        })}
      </div>
    </fieldset>
  );
}

// The Printer Settings pages for one 3MF version's settings (null: there's no 3MF to read them from), followed by
// `extraPages`: pages of Farmhand's own ({ id, title, Icon, render }), such as the sub printer's Printer parts
function PresetPages({ settings, extraPages = [] }) {
  const extruders = Math.max(1, String(settings?.nozzle_diameter ?? "").split(",").filter((s) => s !== "").length);
  const parent = useMemo(() => {
    const parts = String(settings?.inherits_cummulative ?? "").split(";"); // print; filament(s)...; printer
    return parts.length > 1 ? unescape(parts[parts.length - 1]).replace(/^"|"$/g, "") : "";
  }, [settings]);

  const pages = useMemo(() => {
    if (!settings) return extraPages;
    const list = [
      { id: "general", title: "General", Icon: Printer, groups: GENERAL },
      { id: "gcode", title: "Custom G-code", Icon: FileCode, groups: CUSTOM_GCODE },
      { id: "limits", title: "Machine limits", Icon: Gauge, groups: MACHINE_LIMITS },
      ...Array.from({ length: extruders }, (_, i) => ({ id: `extruder${i}`, title: `Extruder ${i + 1}`, Icon: CircleDot, groups: EXTRUDER, extruder: i })),
      { id: "notes", title: "Notes", Icon: StickyNote, groups: NOTES },
      { id: "deps", title: "Dependencies", Icon: Link2, groups: DEPENDENCIES },
    ];
    // printer settings the pages above don't have a place for (BOSS edition has more than PrusaSlicer), so none is lost
    const shown = new Set(list.flatMap((p) => p.groups.flatMap((g) => g.rows.map((r) => r[0]))));
    const rest = Object.keys(settings).filter((k) => !shown.has(k) && !NOT_PRINTER(k) && classifyPrusa(k).tab === "Printer Settings").sort();
    if (rest.length) {
      list.push({ id: "other", title: "Other", Icon: Puzzle, groups: [{ title: "More printer settings in this 3MF", rows: rest.map((k) => [k, k.replace(/_/g, " ").replace(/^./, (ch) => ch.toUpperCase())]) }] });
    }
    return [...list, ...extraPages];
  }, [settings, extruders, extraPages]);

  const [pageId, setPageId] = useState(settings ? "general" : extraPages[0]?.id);
  const page = pages.find((p) => p.id === pageId) || pages[0];
  const value = (key) => {
    if (key === "@extruders") return String(extruders);
    if (key === "@parent") return parent || "(none: it doesn’t inherit from a system preset)";
    return pick(key, settings[key], page.extruder);
  };

  return (
    <div style={{ display: "flex", gap: 14, minHeight: 420 }}>
      <nav aria-label="Printer Settings pages" style={{ width: 170, flexShrink: 0, display: "flex", flexDirection: "column", gap: 2, borderRight: `1px solid ${c.border}`, paddingRight: 10 }}>
        {pages.map((p) => {
          const on = p.id === page.id;
          return (
            <button
              key={p.id}
              data-testid="preset-page"
              aria-current={on ? "page" : undefined}
              onClick={() => setPageId(p.id)}
              style={{
                ...ui, fontSize: fs(13), display: "flex", alignItems: "center", gap: 8, textAlign: "left", padding: "6px 8px",
                borderRadius: 3, border: "none", cursor: "pointer", background: on ? c.amberDim : "transparent", color: on ? c.amber : c.textMuted,
              }}
            >
              <p.Icon size={14} color={on ? c.amber : c.textFaint} />
              {p.title}
            </button>
          );
        })}
      </nav>
      <div data-testid="preset-page-body" style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 12, maxHeight: "62vh", overflowY: "auto", paddingRight: 4 }}>
        {page.render ? page.render() : page.groups.map((g) => <Group key={g.title} group={g} value={value} />)}
      </div>
    </div>
  );
}

// Loads the version's settings, then shows them as the Printer Settings tab, with `extraPages` after them. `name` is the
// preset, shown at the top the way PrusaSlicer's preset drop-down shows it. With no version (no 3MF was sliced with
// it yet) only the extra pages are shown, under `empty`, which says why.
export function PrinterPresetPages({ ver, name, from, extraPages, empty }) {
  const [settings, setSettings] = useState(null);
  const [loadError, setLoadError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setSettings(null);
    setLoadError(null);
    if (!ver) return undefined;
    fetchVersionSettings(ver.id)
      .then((s) => !cancelled && setSettings(s))
      .catch((e) => !cancelled && setLoadError(errorText(e)));
    return () => {
      cancelled = true;
    };
  }, [ver?.id]);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 14 }}>
        <span style={boxStyle({ ...monoText(13, c.heading), padding: "5px 10px", gap: 8 })}>
          <Printer size={14} color={c.teal} />
          {name}
          <ChevronDown size={13} color={c.textFaint} />
        </span>
        {from}
      </div>
      {!ver ? (
        <>
          {empty}
          <PresetPages settings={null} extraPages={extraPages} />
        </>
      ) : loadError ? (
        <div style={uiText(13, c.amber)}>Couldn't load its settings: {loadError}</div>
      ) : !settings ? (
        <div style={uiText(13, c.textFaint)}>Loading settings…</div>
      ) : (
        <PresetPages key={ver.id} settings={settings} extraPages={extraPages} />
      )}
    </div>
  );
}
