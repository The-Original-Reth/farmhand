import {
  Cog, FileCode, Fan, Gauge, Layers, Link2, Paintbrush, Printer, ScrollText, SlidersHorizontal, Spline, SquareStack,
  Thermometer, Waypoints, Wind, Wrench,
} from "lucide-react";
import { classifyPrusa } from "../settingsLayout.js";
import { extruderCount, extruderPages, groupKeys, notesPage, otherPage, pageValue, presetName } from "./pages.js";

// PrusaSlicer (BOSS edition) settings, laid out as its Print Settings, Filament Settings and Printer Settings tabs: the
// same pages down the left, the same titled groups on each page, the same labels and units. A setting with no place
// on these pages (BOSS has more than PrusaSlicer) goes on an "Other" page of its tab, so none is lost.
// Rows: [key, label, kind or unit] (see fields.jsx).

// ------------------------------------------------------------------ Print Settings
const LAYERS = [
  { title: "Layer height", rows: [["layer_height", "Layer height", "mm"], ["first_layer_height", "First layer height", "mm"]] },
  { title: "Vertical shells", rows: [["perimeters", "Perimeters", "(minimum)"], ["spiral_vase", "Spiral vase", "bool"]] },
  {
    title: "Horizontal shells",
    rows: [
      ["top_solid_layers", "Solid layers: Top"], ["bottom_solid_layers", "Solid layers: Bottom"],
      ["top_solid_min_thickness", "Minimum shell thickness: Top", "mm"], ["bottom_solid_min_thickness", "Minimum shell thickness: Bottom", "mm"],
    ],
  },
  {
    title: "Quality (slower slicing)",
    rows: [
      ["extra_perimeters", "Extra perimeters if needed", "bool"], ["extra_perimeters_on_overhangs", "Extra perimeters on overhangs (Experimental)", "bool"],
      ["avoid_crossing_curled_overhangs", "Avoid crossing curled overhangs (Experimental)", "bool"], ["avoid_crossing_perimeters", "Avoid crossing perimeters", "bool"],
      ["avoid_crossing_perimeters_max_detour", "Avoid crossing perimeters - Max detour length", "mm"], ["thin_walls", "Detect thin walls", "bool"],
      ["thick_bridges", "Thick bridges", "bool"], ["overhangs", "Detect bridging perimeters", "bool"],
    ],
  },
  {
    title: "Advanced",
    rows: [
      ["seam_position", "Seam position", "enum"], ["seam_gap_distance", "Seam gap distance", "mm"], ["staggered_inner_seams", "Staggered inner seams", "bool"],
      ["external_perimeters_first", "External perimeters first", "bool"], ["external_perimeters_first_holes", "External perimeters first for holes", "bool"],
      ["external_perimeters_first_holes_min_size", "Minimum hole size for external perimeters first", "mm"],
      ["external_perimeters_first_disabled_first_layers", "Not on the first layers", "layers"], ["gap_fill_enabled", "Fill gaps", "bool"],
      ["perimeter_generator", "Perimeter generator", "enum"], ["alternate_extra_perimeter", "Alternate extra perimeter", "bool"],
      ["internal_perimeters_reverse", "Reverse internal perimeters", "bool"], ["overhangs_reverse", "Reverse on overhangs", "bool"],
      ["prefer_clockwise_movements", "Prefer clockwise movements", "bool"],
      ["small_perimeter_min_length", "Small perimeters: Min length", "mm"], ["small_perimeter_max_length", "Small perimeters: Max length", "mm"],
    ],
  },
  {
    title: "Seam notch",
    rows: [["seam_type", "Seam type", "enum"], ["seam_notch_angle", "Seam notch angle", "°"], ["seam_notch_width", "Seam notch width", "mm"]],
  },
  {
    title: "Scarf joint placement",
    rows: [
      ["scarf_seam_placement", "Scarf joint placement", "enum"], ["scarf_seam_only_on_smooth", "Scarf joint only on smooth perimeters", "bool"],
      ["scarf_seam_start_height", "Scarf start height", "mm"], ["scarf_seam_entire_loop", "Scarf joint around entire perimeter", "bool"],
      ["scarf_seam_length", "Scarf joint length", "mm"], ["scarf_seam_max_segment_length", "Max scarf joint segment length", "mm"],
      ["scarf_seam_on_inner_perimeters", "Scarf joint on inner perimeters", "bool"],
    ],
  },
  {
    title: "Fuzzy skin (experimental)",
    rows: [
      ["fuzzy_skin", "Fuzzy Skin", "enum"], ["fuzzy_skin_thickness", "Fuzzy skin thickness", "mm"], ["fuzzy_skin_point_dist", "Fuzzy skin point distance", "mm"],
      ["fuzzy_skin_noise_type", "Noise type", "enum"], ["fuzzy_skin_feature_size", "Feature size", "mm"], ["fuzzy_skin_octaves", "Octaves"],
      ["fuzzy_skin_persistence", "Persistence"],
    ],
  },
  {
    title: "Only one perimeter",
    rows: [["top_one_perimeter_type", "Single perimeter on top surfaces", "enum"], ["only_one_perimeter_first_layer", "Only one perimeter on first layer", "bool"]],
  },
];
const INFILL = [
  {
    title: "Infill",
    rows: [
      ["fill_density", "Fill density", "%"], ["fill_pattern", "Fill pattern", "enum"], ["infill_anchor", "Length of the infill anchor", "mm"],
      ["infill_anchor_max", "Maximum length of the infill anchor", "mm"], ["top_fill_pattern", "Top fill pattern", "enum"], ["bottom_fill_pattern", "Bottom fill pattern", "enum"],
      ["solid_fill_pattern", "Solid fill pattern", "enum"], ["infill_reverse", "Reverse infill direction", "bool"], ["bridge_density", "Bridge density", "%"],
    ],
  },
  {
    title: "Ironing",
    rows: [["ironing", "Enable ironing", "bool"], ["ironing_type", "Ironing Type", "enum"], ["ironing_flowrate", "Flow rate", "%"], ["ironing_spacing", "Spacing between ironing passes", "mm"]],
  },
  {
    title: "Reducing printing time",
    rows: [
      ["infill_every_layers", "Combine infill every", "layers"], ["automatic_infill_combination", "Automatic infill combination", "bool"],
      ["automatic_infill_combination_max_layer_height", "Max layer height for combining infill", "mm"],
    ],
  },
  {
    title: "Solid infill",
    rows: [
      ["ensure_vertical_shell_thickness", "Ensure vertical shell thickness", "enum"], ["detect_narrow_solid_infill", "Detect narrow solid infill", "bool"],
      ["detect_narrow_solid_infill_threshold", "Narrow solid infill threshold", "mm"],
    ],
  },
  {
    title: "Advanced",
    rows: [
      ["solid_infill_every_layers", "Solid infill every", "layers"], ["fill_angle", "Fill angle", "°"], ["solid_infill_below_area", "Solid infill threshold area", "mm²"],
      ["bridge_angle", "Bridging angle", "°"], ["only_retract_when_crossing_perimeters", "Only retract when crossing perimeters", "bool"], ["infill_first", "Infill before perimeters", "bool"],
    ],
  },
];
const SKIRT_BRIM = [
  {
    title: "Skirt",
    rows: [
      ["skirts", "Loops (minimum)"], ["skirt_distance", "Distance from brim/object", "mm"], ["skirt_height", "Skirt height", "layers"],
      ["draft_shield", "Draft shield", "enum"], ["min_skirt_length", "Minimal filament extrusion length", "mm"],
    ],
  },
  { title: "Brim", rows: [["brim_type", "Brim type", "enum"], ["brim_width", "Brim width", "mm"], ["brim_separation", "Brim separation gap", "mm"]] },
];
const SUPPORT = [
  {
    title: "Support material",
    rows: [
      ["support_material", "Generate support material", "bool"], ["support_material_auto", "Auto generated supports", "bool"],
      ["support_material_threshold", "Overhang threshold", "°"], ["support_material_enforce_layers", "Enforce support for the first", "layers"],
      ["raft_first_layer_density", "First layer density", "%"], ["raft_first_layer_expansion", "First layer expansion", "mm"],
    ],
  },
  { title: "Raft", rows: [["raft_layers", "Raft layers", "layers"], ["raft_contact_distance", "Raft contact Z distance", "mm"], ["raft_expansion", "Raft expansion", "mm"]] },
  {
    title: "Options for support material and raft",
    rows: [
      ["support_material_style", "Style", "enum"], ["support_material_contact_distance", "Top contact Z distance", "mm"],
      ["support_material_bottom_contact_distance", "Bottom contact Z distance", "mm"], ["support_material_pattern", "Pattern", "enum"],
      ["support_material_with_sheath", "With sheath around the support", "bool"], ["support_material_spacing", "Pattern spacing", "mm"],
      ["support_material_angle", "Pattern angle", "°"], ["support_material_closing_radius", "Closing radius", "mm"],
      ["support_material_interface_layers", "Top interface layers", "layers"], ["support_material_bottom_interface_layers", "Bottom interface layers", "layers"],
      ["support_material_interface_pattern", "Interface pattern", "enum"], ["support_material_interface_spacing", "Interface pattern spacing", "mm"],
      ["support_material_interface_contact_loops", "Interface loops", "bool"], ["support_material_buildplate_only", "Support on build plate only", "bool"],
      ["support_material_xy_spacing", "XY separation between an object and its support", "mm"], ["dont_support_bridges", "Don't support bridges", "bool"],
      ["support_material_synchronize_layers", "Synchronize with object layers", "bool"],
    ],
  },
  {
    title: "Organic supports",
    rows: [
      ["support_tree_angle", "Maximum Branch Angle", "°"], ["support_tree_angle_slow", "Preferred Branch Angle", "°"],
      ["support_tree_branch_diameter", "Branch Diameter", "mm"], ["support_tree_branch_diameter_angle", "Branch Diameter Angle", "°"],
      ["support_tree_branch_diameter_double_wall", "Branch Diameter with double walls", "mm"], ["support_tree_tip_diameter", "Tip Diameter", "mm"],
      ["support_tree_branch_distance", "Branch Distance"], ["support_tree_top_rate", "Branch Density", "%"],
    ],
  },
];
const SPEED = [
  {
    title: "Speed for print moves",
    rows: [
      ["perimeter_speed", "Perimeters", "mm/s"], ["small_perimeter_speed", "Small perimeters", "mm/s"], ["external_perimeter_speed", "External perimeters", "mm/s"],
      ["infill_speed", "Infill", "mm/s"], ["solid_infill_speed", "Solid infill", "mm/s"], ["top_solid_infill_speed", "Top solid infill", "mm/s"],
      ["support_material_speed", "Support material", "mm/s"], ["support_material_interface_speed", "Support material interface", "mm/s"],
      ["bridge_speed", "Bridges", "mm/s"], ["over_bridge_speed", "Over bridges", "mm/s"], ["gap_fill_speed", "Gap fill", "mm/s"], ["ironing_speed", "Ironing", "mm/s"],
    ],
  },
  {
    title: "Dynamic overhang speed",
    rows: [
      ["enable_dynamic_overhang_speeds", "Enable dynamic overhang speeds", "bool"], ["overhang_speed_0", "speed for 0% overlap (bridge)", "mm/s"],
      ["overhang_speed_1", "speed for 25% overlap", "mm/s"], ["overhang_speed_2", "speed for 50% overlap", "mm/s"], ["overhang_speed_3", "speed for 75% overlap", "mm/s"],
    ],
  },
  { title: "Speed for non-print moves", rows: [["travel_speed", "Travel", "mm/s"], ["travel_speed_z", "Z travel", "mm/s"]] },
  {
    title: "Modifiers",
    rows: [
      ["first_layer_speed", "First layer speed", "mm/s"], ["first_layer_infill_speed", "First layer infill speed", "mm/s"],
      ["first_layer_speed_over_raft", "Speed of object first layer over raft interface", "mm/s"],
    ],
  },
  {
    title: "Acceleration control (advanced)",
    rows: [
      ["external_perimeter_acceleration", "External perimeters", "mm/s²"], ["perimeter_acceleration", "Perimeters", "mm/s²"],
      ["top_solid_infill_acceleration", "Top solid infill", "mm/s²"], ["solid_infill_acceleration", "Solid infill", "mm/s²"],
      ["infill_acceleration", "Infill", "mm/s²"], ["bridge_acceleration", "Bridge", "mm/s²"], ["first_layer_acceleration", "First layer", "mm/s²"],
      ["first_layer_acceleration_over_raft", "First object layer over raft interface", "mm/s²"], ["wipe_tower_acceleration", "Wipe tower", "mm/s²"],
      ["travel_acceleration", "Travel", "mm/s²"], ["travel_short_distance_acceleration", "Short travel", "mm/s²"], ["default_acceleration", "Default", "mm/s²"],
    ],
  },
  {
    title: "Jerk control (advanced)",
    rows: [
      ["external_perimeter_jerk", "External perimeters", "mm/s"], ["perimeter_jerk", "Perimeters", "mm/s"], ["top_solid_infill_jerk", "Top solid infill", "mm/s"],
      ["solid_infill_jerk", "Solid infill", "mm/s"], ["infill_jerk", "Infill", "mm/s"], ["bridge_jerk", "Bridge", "mm/s"], ["first_layer_jerk", "First layer", "mm/s"],
      ["first_layer_jerk_over_raft", "First object layer over raft interface", "mm/s"], ["wipe_tower_jerk", "Wipe tower", "mm/s"],
      ["travel_jerk", "Travel", "mm/s"], ["travel_short_distance_jerk", "Short travel", "mm/s"], ["default_jerk", "Default", "mm/s"],
    ],
  },
  {
    title: "Minimum cruise ratio (advanced)",
    rows: [
      ["external_perimeter_minimum_cruise_ratio", "External perimeters", "%"], ["perimeter_minimum_cruise_ratio", "Perimeters", "%"],
      ["top_solid_infill_minimum_cruise_ratio", "Top solid infill", "%"], ["solid_infill_minimum_cruise_ratio", "Solid infill", "%"],
      ["infill_minimum_cruise_ratio", "Infill", "%"], ["bridge_minimum_cruise_ratio", "Bridge", "%"], ["first_layer_minimum_cruise_ratio", "First layer", "%"],
      ["first_layer_minimum_cruise_ratio_over_raft", "First object layer over raft interface", "%"], ["wipe_tower_minimum_cruise_ratio", "Wipe tower", "%"],
      ["travel_minimum_cruise_ratio", "Travel", "%"], ["travel_short_distance_minimum_cruise_ratio", "Short travel", "%"], ["default_minimum_cruise_ratio", "Default", "%"],
    ],
  },
  { title: "Autospeed (advanced)", rows: [["max_print_speed", "Max print speed", "mm/s"], ["max_volumetric_speed", "Max volumetric speed", "mm³/s"]] },
  {
    title: "Pressure equalizer (experimental)",
    rows: [
      ["max_volumetric_extrusion_rate_slope_positive", "Max volumetric slope positive", "mm³/s²"],
      ["max_volumetric_extrusion_rate_slope_negative", "Max volumetric slope negative", "mm³/s²"],
    ],
  },
];
const MULTI_EXTRUDERS = [
  {
    title: "Extruders",
    rows: [
      ["perimeter_extruder", "Perimeter extruder"], ["infill_extruder", "Infill extruder"], ["solid_infill_extruder", "Solid infill extruder"],
      ["support_material_extruder", "Support material/raft/skirt extruder"], ["support_material_interface_extruder", "Support material/raft interface extruder"],
      ["wipe_tower_extruder", "Wipe tower extruder"],
    ],
  },
  {
    title: "Ooze prevention",
    rows: [["ooze_prevention", "Enable", "bool"], ["standby_temperature_delta", "Temperature variation", "°C"], ["preheat_time", "Preheat time", "s"], ["preheat_steps", "Preheat steps"]],
  },
  {
    title: "Wipe tower",
    rows: [
      ["wipe_tower", "Enable", "bool"], ["wipe_tower_width", "Width", "mm"], ["wipe_tower_brim_width", "Wipe tower brim width", "mm"],
      ["wipe_tower_bridging", "Maximal bridging distance", "mm"], ["wipe_tower_cone_angle", "Stabilization cone apex angle", "°"],
      ["wipe_tower_extra_spacing", "Wipe tower purge lines spacing", "%"], ["wipe_tower_extra_flow", "Extra flow for purging", "%"],
      ["wipe_tower_no_sparse_layers", "No sparse layers (beta)", "bool"], ["single_extruder_multi_material_priming", "Prime all printing extruders", "bool"],
      ["wipe_tower_x", "Position X", "mm"], ["wipe_tower_y", "Position Y", "mm"], ["wipe_tower_rotation_angle", "Rotation angle", "°"],
      ["wipe_tower_max_purge_speed", "Maximum purge speed", "mm/s"], ["wipe_tower_disable_filament_ramming", "Disable filament ramming", "bool"],
      ["wipe_tower_disable_linear_advance", "Disable linear advance", "bool"], ["toolchange_ordering", "Tool change ordering", "enum"],
      ["wipe_into_infill", "Wipe into this object's infill", "bool"], ["wipe_into_objects", "Wipe into this object", "bool"],
      ["wiping_volumes_use_custom_matrix", "Use custom purging volumes", "bool"], ["wiping_volumes_matrix", "Purging volumes"],
    ],
  },
  {
    title: "Interlocking",
    rows: [
      ["interlocking_beam", "Use beam interlocking", "bool"], ["interlocking_beam_width", "Beam width", "mm"], ["interlocking_orientation", "Direction", "°"],
      ["interlocking_beam_layer_count", "Beam layers"], ["interlocking_depth", "Depth"], ["interlocking_boundary_avoidance", "Boundary avoidance"],
    ],
  },
  {
    title: "Advanced",
    rows: [
      ["interface_shells", "Interface shells", "bool"], ["mmu_segmented_region_max_width", "Maximum width of a segmented region", "mm"],
      ["mmu_segmented_region_interlocking_depth", "Interlocking depth of a segmented region", "mm"],
    ],
  },
];
const PRINT_ADVANCED = [
  {
    title: "Extrusion width",
    rows: [
      ["extrusion_width", "Default extrusion width", "mm"], ["first_layer_extrusion_width", "First layer", "mm"], ["perimeter_extrusion_width", "Perimeters", "mm"],
      ["external_perimeter_extrusion_width", "External perimeters", "mm"], ["infill_extrusion_width", "Infill", "mm"], ["solid_infill_extrusion_width", "Solid infill", "mm"],
      ["top_infill_extrusion_width", "Top solid infill", "mm"], ["support_material_extrusion_width", "Support material", "mm"],
    ],
  },
  { title: "Automatic extrusion widths", rows: [["automatic_extrusion_widths", "Automatic extrusion widths", "bool"]] },
  {
    title: "Overlap",
    rows: [
      ["infill_overlap", "Infill/perimeters overlap", "mm"], ["external_perimeter_overlap", "External perimeter overlap", "%"],
      ["perimeter_perimeter_overlap", "Perimeter overlap", "%"],
    ],
  },
  {
    title: "Flow",
    rows: [
      ["bridge_flow_ratio", "Bridge flow ratio"], ["first_layer_flow_ratio", "First layer flow ratio"], ["top_layer_flow_ratio", "Top layer flow ratio"],
      ["print_extrusion_multiplier", "Extrusion multiplier"],
    ],
  },
  {
    title: "Small area infill flow compensation",
    rows: [
      ["small_area_infill_flow_compensation", "Enable", "bool"],
      ...Array.from({ length: 10 }, (_, i) => [
        [`small_area_infill_flow_compensation_extrusion_length_${i}`, `Extrusion length ${i + 1}`, "mm"],
        [`small_area_infill_flow_compensation_compensation_factor_${i}`, `Compensation factor ${i + 1}`],
      ]).flat(),
    ],
  },
  {
    title: "Slicing",
    rows: [
      ["slice_closing_radius", "Slice gap closing radius", "mm"], ["slicing_mode", "Slicing Mode", "enum"], ["resolution", "Slice resolution", "mm"],
      ["gcode_resolution", "G-code resolution", "mm"], ["arc_fitting", "Arc fitting", "enum"], ["xy_size_compensation", "XY Size Compensation", "mm"],
      ["elefant_foot_compensation", "Elephant foot compensation", "mm"],
    ],
  },
  {
    title: "Arachne perimeter generator",
    rows: [
      ["wall_transition_angle", "Perimeter transitioning threshold angle", "°"], ["wall_transition_filter_deviation", "Perimeter transitioning filter margin", "mm"],
      ["wall_transition_length", "Perimeter transition length", "mm"], ["wall_distribution_count", "Perimeter distribution count"],
      ["min_bead_width", "Minimum perimeter width", "mm"], ["min_feature_size", "Minimum feature size", "mm"],
    ],
  },
];
const OUTPUT = [
  {
    title: "Sequential printing",
    rows: [["complete_objects", "Complete individual objects", "bool"], ["extruder_clearance_radius", "Extruder clearance: Radius", "mm"], ["extruder_clearance_height", "Extruder clearance: Height", "mm"]],
  },
  {
    title: "Output file",
    rows: [["gcode_comments", "Verbose G-code", "bool"], ["gcode_label_objects", "Label objects", "enum"], ["output_filename_format", "Output filename format"]],
  },
  { title: "Other", rows: [["gcode_substitutions", "G-code substitutions"]] },
  { title: "Post-processing scripts", rows: [["post_process", "", "gcode"]] },
];

// ------------------------------------------------------------------ Filament Settings
const FILAMENT = [
  {
    title: "Filament",
    rows: [
      ["filament_colour", "Color", "color"], ["filament_diameter", "Diameter", "mm"], ["extrusion_multiplier", "Extrusion multiplier"],
      ["filament_density", "Density", "g/cm³"], ["filament_cost", "Cost", "money/kg"], ["filament_spool_weight", "Spool weight", "g"],
      ["filament_vendor", "Vendor"], ["filament_shrinkage_compensation_xy", "Shrinkage compensation: XY", "%"],
      ["filament_shrinkage_compensation_z", "Shrinkage compensation: Z", "%"],
    ],
  },
  {
    title: "Temperature",
    rows: [
      ["idle_temperature", "Idle temperature", "°C"], ["first_layer_temperature", "Nozzle: First layer", "°C"], ["temperature", "Nozzle: Other layers", "°C"],
      ["first_layer_bed_temperature", "Bed: First layer", "°C"], ["bed_temperature", "Bed: Other layers", "°C"],
      ["chamber_temperature", "Chamber: Nominal", "°C"], ["chamber_minimal_temperature", "Chamber: Minimal", "°C"],
    ],
  },
];
const COOLING = [
  { title: "Enable", rows: [["fan_always_on", "Keep fan always on", "bool"], ["cooling", "Enable auto cooling", "bool"]] },
  {
    title: "Fan settings",
    rows: [
      ["min_fan_speed", "Fan speed: Min", "%"], ["max_fan_speed", "Fan speed: Max", "%"], ["bridge_fan_speed", "Bridges fan speed", "%"],
      ["disable_fan_first_layers", "Disable fan for the first", "layers"], ["full_fan_speed_layer", "Full fan speed at layer"],
    ],
  },
  {
    title: "Dynamic fan speeds",
    rows: [
      ["enable_dynamic_fan_speeds", "Enable dynamic fan speeds", "bool"], ["overhang_fan_speed_0", "speed for 0% overlap (bridge)", "%"],
      ["overhang_fan_speed_1", "speed for 25% overlap", "%"], ["overhang_fan_speed_2", "speed for 50% overlap", "%"], ["overhang_fan_speed_3", "speed for 75% overlap", "%"],
    ],
  },
  {
    title: "Cooling thresholds",
    rows: [
      ["fan_below_layer_time", "Enable fan if layer print time is below", "s"], ["slowdown_below_layer_time", "Slow down if layer print time is below", "s"],
      ["min_print_speed", "Min print speed", "mm/s"], ["cooling_slowdown_logic", "Slowdown logic", "enum"],
      ["cooling_perimeter_transition_distance", "Perimeter transition distance", "mm"],
    ],
  },
];
const FILAMENT_ADVANCED = [
  { title: "Filament properties", rows: [["filament_type", "Filament type", "enum"], ["filament_soluble", "Soluble material", "bool"], ["filament_abrasive", "Abrasive material", "bool"]] },
  {
    title: "Print speed override",
    rows: [
      ["filament_max_volumetric_speed", "Max volumetric speed", "mm³/s"], ["filament_max_speed", "Max speed", "mm/s"],
      ["filament_infill_max_speed", "Max infill speed", "mm/s"], ["filament_infill_max_crossing_speed", "Max infill crossing speed", "mm/s"],
    ],
  },
  { title: "Wipe tower parameters", rows: [["filament_minimal_purge_on_wipe_tower", "Minimal purge on wipe tower", "mm³"]] },
  {
    title: "Toolchange parameters with single extruder MM printers",
    rows: [
      ["filament_loading_speed_start", "Loading speed at the start", "mm/s"], ["filament_loading_speed", "Loading speed", "mm/s"],
      ["filament_unloading_speed_start", "Unloading speed at the start", "mm/s"], ["filament_unloading_speed", "Unloading speed", "mm/s"],
      ["filament_toolchange_delay", "Delay after unloading", "s"], ["filament_cooling_moves", "Number of cooling moves"],
      ["filament_cooling_initial_speed", "Speed of the first cooling move", "mm/s"], ["filament_cooling_final_speed", "Speed of the last cooling move", "mm/s"],
      ["filament_stamping_loading_speed", "Stamping loading speed", "mm/s"], ["filament_stamping_distance", "Stamping distance", "mm"],
      ["filament_ramming_parameters", "Ramming parameters"], ["filament_load_time", "Filament load time", "s"],
      ["filament_unload_time", "Filament unload time", "s"], ["filament_purge_multiplier", "Purge multiplier", "%"],
      ["filament_prime_length_at_start", "Prime length at start", "mm"], ["wipe_tower_disable_cooling_moves", "Disable cooling moves on the wipe tower", "bool"],
    ],
  },
  {
    title: "Toolchange parameters with multi extruder MM printers",
    rows: [
      ["filament_multitool_ramming", "Enable ramming for multitool setups", "bool"], ["filament_multitool_ramming_volume", "Multitool ramming volume", "mm³"],
      ["filament_multitool_ramming_flow", "Multitool ramming flow", "mm³/s"],
    ],
  },
];
const OVERRIDES = [
  {
    title: "Travel lift",
    rows: [
      ["filament_retract_lift", "Lift height", "mm"], ["filament_travel_ramping_lift", "Ramping lift", "bool"], ["filament_travel_max_lift", "Maximum ramping lift", "mm"],
      ["filament_travel_slope", "Ramping slope angle", "°"], ["filament_travel_lift_before_obstacle", "Steeper ramp before obstacles", "bool"],
    ],
  },
  { title: "Only lift", rows: [["filament_retract_lift_above", "Above Z", "mm"], ["filament_retract_lift_below", "Below Z", "mm"]] },
  {
    title: "Retraction",
    rows: [
      ["filament_retract_length", "Length", "mm"], ["filament_retract_speed", "Retraction Speed", "mm/s"], ["filament_deretract_speed", "Deretraction Speed", "mm/s"],
      ["filament_retract_restart_extra", "Extra length on restart", "mm"], ["filament_retract_before_travel", "Minimum travel after retraction", "mm"],
      ["filament_retract_layer_change", "Retract on layer change", "bool"], ["filament_wipe", "Wipe while retracting", "bool"],
      ["filament_retract_before_wipe", "Retract amount before wipe", "%"],
    ],
  },
  {
    title: "Retraction when tool is disabled",
    rows: [["filament_retract_length_toolchange", "Length", "mm"], ["filament_retract_restart_extra_toolchange", "Extra length on restart", "mm"]],
  },
  { title: "Seams", rows: [["filament_seam_gap_distance", "Seam gap distance", "mm"]] },
];
const FILAMENT_GCODE = [
  { title: "Start G-code", rows: [["start_filament_gcode", "", "gcode"]] },
  { title: "End G-code", rows: [["end_filament_gcode", "", "gcode"]] },
];

// ------------------------------------------------------------------ Printer Settings (also the printer profile window)
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
// Printer-looking settings that PrusaSlicer keeps on its Print or Filament tabs, so not on the Printer pages
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
// One page per extruder: these keys hold a value per extruder
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
const PER_EXTRUDER = new Set(groupKeys(EXTRUDER));

// How PrusaSlicer names the choices in its drop-downs
export const BOSS_CHOICES = {
  gcode_flavor: {
    reprap: "RepRap/Sprinter", reprapfirmware: "RepRapFirmware", repetier: "Repetier", teacup: "Teacup", makerware: "MakerWare (MakerBot)",
    marlin: "Marlin (legacy)", marlin2: "Marlin 2", klipper: "Klipper", sailfish: "Sailfish (MakerBot)", mach3: "Mach3/LinuxCNC",
    machinekit: "Machinekit", smoothie: "Smoothie", "no-extrusion": "No extrusion",
  },
  machine_limits_usage: { emit_to_gcode: "Emit to G-code", time_estimate_only: "Use for time estimate", ignore: "Ignore" },
  retract_lift_enforce: { all_surfaces: "All surfaces", first_layer: "First layer only", bottom_solid: "Bottom solid surfaces", top_solid: "Top solid surfaces", bottom_top_solid: "Bottom and top surfaces" },
  seam_position: { random: "Random", nearest: "Nearest", aligned: "Aligned", rear: "Rear" },
  perimeter_generator: { classic: "Classic", arachne: "Arachne" },
  fill_pattern: {
    rectilinear: "Rectilinear", alignedrectilinear: "Aligned Rectilinear", grid: "Grid", triangles: "Triangles", stars: "Stars", cubic: "Cubic",
    line: "Line", concentric: "Concentric", honeycomb: "Honeycomb", "3dhoneycomb": "3D Honeycomb", gyroid: "Gyroid", hilbertcurve: "Hilbert Curve",
    archimedeanchords: "Archimedean Chords", octagramspiral: "Octagram Spiral", adaptivecubic: "Adaptive Cubic", supportcubic: "Support Cubic", lightning: "Lightning",
    monotonic: "Monotonic", monotoniclines: "Monotonic Lines",
  },
  support_material_style: { grid: "Grid", snug: "Snug", organic: "Organic" },
  brim_type: { no_brim: "No brim", outer_only: "Outer brim only", inner_only: "Inner brim only", outer_and_inner: "Outer and inner brim" },
  draft_shield: { disabled: "Disabled", limited: "Limited", enabled: "Enabled" },
  fuzzy_skin: { none: "None", external: "Outside walls", all: "All walls" },
  ironing_type: { top: "All top surfaces", topmost: "Topmost surface only", solid: "All solid surfaces" },
  gcode_label_objects: { disabled: "Disabled", octoprint: "OctoPrint comments", firmware: "Firmware-specific" },
  arc_fitting: { disabled: "Disabled", emit_center: "Enabled" },
  slicing_mode: { regular: "Regular", even_odd: "Even-odd", close_holes: "Close holes" },
  top_one_perimeter_type: { none: "None", all: "All top surfaces", topmost: "Topmost surface only" },
  scarf_seam_placement: { nowhere: "Nowhere", contours: "Contours", everywhere: "Everywhere" },
};
for (const k of ["top_fill_pattern", "bottom_fill_pattern", "support_material_pattern", "support_material_interface_pattern"]) BOSS_CHOICES[k] = BOSS_CHOICES.fill_pattern;

// inherits_cummulative: "print parent; filament parent(s)...; printer parent"
const parents = (settings) => String(settings?.inherits_cummulative ?? "").split(";").map(presetName);
const dependencies = (current, parentKey, extra = []) => [
  { title: "Profile dependencies", rows: [[current, "Current preset"], [parentKey, "Parent preset"], ...extra] },
];

// The Printer Settings pages for these settings, followed by `extraPages` of Farmhand's own
export function bossPrinterPages(settings, extraPages = []) {
  if (!settings) return extraPages;
  const list = [
    { id: "general", title: "General", Icon: Printer, groups: GENERAL },
    { id: "gcode", title: "Custom G-code", Icon: FileCode, groups: CUSTOM_GCODE },
    { id: "limits", title: "Machine limits", Icon: Gauge, groups: MACHINE_LIMITS },
    ...extruderPages(extruderCount(settings), EXTRUDER),
    notesPage("printer_notes"),
    {
      id: "deps", title: "Dependencies", Icon: Link2,
      groups: dependencies("printer_settings_id", "@printerParent", [["printer_vendor", "Vendor"], ["printer_model", "Printer model"], ["printer_variant", "Variant"], ["printer_technology", "Printer technology"]]),
    },
  ];
  // printer settings the pages above don't have a place for (BOSS edition has more than PrusaSlicer), so none is lost
  list.push(...otherPage(settings, list, (k) => !NOT_PRINTER(k) && classifyPrusa(k).tab === "Printer Settings", "More printer settings in this 3MF"));
  return [...list, ...extraPages];
}

// A setting as a BOSS page shows it: "@" ones are worked out, and an Extruder page shows its own extruder's value
export function bossValue(settings) {
  const p = parents(settings);
  const none = "(none: it doesn’t inherit from a system preset)";
  const read = pageValue(settings, PER_EXTRUDER);
  return (key, page) => {
    if (!settings) return undefined;
    if (key === "@extruders") return String(extruderCount(settings));
    if (key === "@printParent") return p.length > 1 ? p[0] || none : none;
    if (key === "@filamentParent") return p.length > 2 ? p.slice(1, -1).filter(Boolean).join("; ") || none : none;
    if (key === "@printerParent") return p.length > 1 ? p[p.length - 1] || none : none;
    return read(key, page);
  };
}

// The three tabs, as PrusaSlicer BOSS edition shows them
export function bossTabs(settings) {
  const printPages = [
    { id: "layers", title: "Layers and perimeters", Icon: Layers, groups: LAYERS },
    { id: "infill", title: "Infill", Icon: SquareStack, groups: INFILL },
    { id: "skirt", title: "Skirt and brim", Icon: Spline, groups: SKIRT_BRIM },
    { id: "support", title: "Support material", Icon: Waypoints, groups: SUPPORT },
    { id: "speed", title: "Speed", Icon: Gauge, groups: SPEED },
    { id: "multi", title: "Multiple Extruders", Icon: Paintbrush, groups: MULTI_EXTRUDERS },
    { id: "advanced", title: "Advanced", Icon: Cog, groups: PRINT_ADVANCED },
    { id: "output", title: "Output options", Icon: ScrollText, groups: OUTPUT },
    notesPage("notes"),
    { id: "deps", title: "Dependencies", Icon: Link2, groups: dependencies("print_settings_id", "@printParent") },
  ];
  const filamentPages = [
    { id: "filament", title: "Filament", Icon: Thermometer, groups: FILAMENT },
    { id: "cooling", title: "Cooling", Icon: Fan, groups: COOLING },
    { id: "advanced", title: "Advanced", Icon: Wrench, groups: FILAMENT_ADVANCED },
    { id: "overrides", title: "Filament Overrides", Icon: SlidersHorizontal, groups: OVERRIDES },
    { id: "gcode", title: "Custom G-code", Icon: FileCode, groups: FILAMENT_GCODE },
    notesPage("filament_notes"),
    { id: "deps", title: "Dependencies", Icon: Link2, groups: dependencies("filament_settings_id", "@filamentParent") },
  ];
  const printerPages = bossPrinterPages(settings);
  const all = [...printPages, ...filamentPages, ...printerPages];
  printPages.push(...otherPage(settings, all, (k) => classifyPrusa(k).tab === "Print Settings" && !k.endsWith("_settings_id"), "More print settings in this 3MF"));
  filamentPages.push(...otherPage(settings, all, (k) => classifyPrusa(k).tab === "Filament Settings", "More filament settings in this 3MF"));
  return [
    { id: "print", title: "Print Settings", Icon: Layers, presetKey: "print_settings_id", pages: printPages },
    { id: "filament", title: "Filament Settings", Icon: Wind, presetKey: "filament_settings_id", pages: filamentPages },
    { id: "printer", title: "Printer Settings", Icon: Printer, presetKey: "printer_settings_id", pages: printerPages },
  ];
}
