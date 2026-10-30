import {
  Box, CircleDot, Cog, Fan, FileCode, Gauge, Layers, Link2, Paintbrush, Printer, Puzzle, Shield, SlidersHorizontal,
  SquareStack, StickyNote, Thermometer, Waypoints, Wind, Wrench,
} from "lucide-react";
import { keyLabel, nth, placedKeys } from "./fields.jsx";

// OrcaSlicer (and Bambu Studio, whose format it writes) settings, laid out as Orca shows them: the Process settings
// with their tabs across the top (Quality, Strength, Speed, Support, Multimaterial, Others), and the Filament and
// Printer settings windows with theirs. A setting with no place on these pages goes on an "Other" page of the tab it
// belongs to, so none is lost. Rows: [key, label, kind or unit] (see fields.jsx).

// ------------------------------------------------------------------ Process
const QUALITY = [
  { title: "Layer height", rows: [["layer_height", "Layer height", "mm"], ["initial_layer_print_height", "Initial layer height", "mm"]] },
  {
    title: "Line width",
    rows: [
      ["line_width", "Default", "mm"], ["initial_layer_line_width", "Initial layer", "mm"], ["outer_wall_line_width", "Outer wall", "mm"],
      ["inner_wall_line_width", "Inner wall", "mm"], ["top_surface_line_width", "Top surface", "mm"], ["sparse_infill_line_width", "Sparse infill", "mm"],
      ["internal_solid_infill_line_width", "Internal solid infill", "mm"], ["support_line_width", "Support", "mm"],
    ],
  },
  {
    title: "Seam",
    rows: [
      ["seam_position", "Seam position", "enum"], ["staggered_inner_seams", "Staggered inner seams", "bool"], ["seam_gap", "Seam gap", "mm"],
      ["seam_slope_type", "Scarf joint seam (beta)", "enum"], ["seam_slope_conditional", "Conditional scarf joint", "bool"],
      ["scarf_angle_threshold", "Conditional angle threshold", "°"], ["scarf_overhang_threshold", "Conditional overhang threshold", "%"],
      ["scarf_joint_speed", "Scarf joint speed", "mm/s"], ["scarf_joint_flow_ratio", "Scarf joint flow ratio"],
      ["seam_slope_start_height", "Scarf start height", "mm"], ["seam_slope_entire_loop", "Scarf around entire wall", "bool"],
      ["seam_slope_min_length", "Scarf length", "mm"], ["seam_slope_steps", "Scarf steps"], ["seam_slope_inner_walls", "Scarf joint for inner walls", "bool"],
      ["role_based_wipe_speed", "Role base wipe speed", "bool"], ["wipe_speed", "Wipe speed", "mm/s"], ["wipe_on_loops", "Wipe on loops", "bool"],
      ["wipe_before_external_loop", "Wipe before external loop", "bool"],
    ],
  },
  {
    title: "Precision",
    rows: [
      ["slice_closing_radius", "Slice gap closing radius", "mm"], ["resolution", "Resolution", "mm"], ["enable_arc_fitting", "Arc fitting", "bool"],
      ["xy_hole_compensation", "X-Y hole compensation", "mm"], ["xy_contour_compensation", "X-Y contour compensation", "mm"],
      ["elefant_foot_compensation", "Elephant foot compensation", "mm"], ["elefant_foot_compensation_layers", "Elephant foot compensation layers", "layers"],
      ["precise_outer_wall", "Precise wall", "bool"], ["precise_z_height", "Precise Z height", "bool"],
      ["hole_to_polyhole", "Convert holes to polyholes", "bool"], ["hole_to_polyhole_threshold", "Polyhole detection margin", "mm"],
      ["hole_to_polyhole_twisted", "Polyhole twist", "bool"], ["wall_maximum_resolution", "Maximum wall resolution", "mm"],
      ["wall_maximum_deviation", "Maximum wall deviation", "mm"],
    ],
  },
  {
    title: "Ironing",
    rows: [
      ["ironing_type", "Ironing type", "enum"], ["ironing_pattern", "Ironing pattern", "enum"], ["ironing_flow", "Ironing flow", "%"],
      ["ironing_spacing", "Ironing line spacing", "mm"], ["ironing_inset", "Ironing inset", "mm"], ["ironing_angle", "Ironing angle", "°"],
      ["ironing_angle_fixed", "Fixed ironing angle", "bool"], ["ironing_expansion", "Ironing expansion", "mm"],
    ],
  },
  {
    title: "Wall generator",
    rows: [
      ["wall_generator", "Wall generator", "enum"], ["wall_transition_angle", "Wall transitioning threshold angle", "°"],
      ["wall_transition_filter_deviation", "Wall transitioning filter margin", "%"], ["wall_transition_length", "Wall transition length", "%"],
      ["wall_distribution_count", "Wall distribution count"], ["initial_layer_min_bead_width", "First layer minimum wall width", "%"],
      ["min_bead_width", "Minimum wall width", "%"], ["min_feature_size", "Minimum feature size", "%"], ["min_length_factor", "Minimum wall length"],
    ],
  },
  {
    title: "Walls and surfaces",
    rows: [
      ["wall_sequence", "Walls printing order", "enum"], ["is_infill_first", "Print infill first", "bool"], ["wall_direction", "Wall loop direction", "enum"],
      ["print_flow_ratio", "Surface flow ratio"], ["top_solid_infill_flow_ratio", "Top surface flow ratio"], ["bottom_solid_infill_flow_ratio", "Bottom surface flow ratio"],
      ["only_one_wall_top", "Only one wall on top surfaces", "bool"], ["min_width_top_surface", "One wall threshold", "mm"],
      ["only_one_wall_first_layer", "Only one wall on first layer", "bool"], ["reduce_crossing_wall", "Avoid crossing walls", "bool"],
      ["max_travel_detour_distance", "Avoid crossing walls - Max detour length", "mm"], ["small_area_infill_flow_compensation", "Small area flow compensation (beta)", "bool"],
      ["small_area_infill_flow_compensation_model", "Flow compensation model", "gcode"],
    ],
  },
  {
    title: "Flow ratios",
    rows: [
      ["set_other_flow_ratios", "Set other flow ratios", "bool"], ["first_layer_flow_ratio", "First layer"], ["outer_wall_flow_ratio", "Outer wall"],
      ["inner_wall_flow_ratio", "Inner wall"], ["overhang_flow_ratio", "Overhang perimeter"], ["sparse_infill_flow_ratio", "Sparse infill"],
      ["internal_solid_infill_flow_ratio", "Internal solid infill"], ["gap_fill_flow_ratio", "Gap fill"], ["support_flow_ratio", "Support"],
      ["support_interface_flow_ratio", "Support interface"], ["spiral_starting_flow_ratio", "Spiral starting"], ["spiral_finishing_flow_ratio", "Spiral finishing"],
    ],
  },
  {
    title: "Bridging",
    rows: [
      ["bridge_flow", "Bridge flow ratio"], ["internal_bridge_flow", "Internal bridge flow ratio"], ["bridge_density", "Bridge density", "%"],
      ["internal_bridge_density", "Internal bridge density", "%"], ["thick_bridges", "Thick external bridges", "bool"],
      ["thick_internal_bridges", "Thick internal bridges", "bool"], ["enable_extra_bridge_layer", "Extra bridge layers (beta)", "enum"],
      ["dont_filter_internal_bridges", "Filter out small internal bridges", "enum"], ["counterbore_hole_bridging", "Bridge counterbore holes", "enum"],
      ["bridge_angle", "External bridge infill direction", "°"], ["internal_bridge_angle", "Internal bridge infill direction", "°"],
      ["relative_bridge_angle", "Relative bridge infill direction", "bool"], ["bridge_line_width", "Bridge line width", "%"],
    ],
  },
  {
    title: "Overhangs",
    rows: [
      ["detect_overhang_wall", "Detect overhang wall", "bool"], ["make_overhang_printable", "Make overhangs printable", "bool"],
      ["make_overhang_printable_angle", "Make overhangs printable - Maximum angle", "°"], ["make_overhang_printable_hole_size", "Make overhangs printable - Hole area", "mm²"],
      ["extra_perimeters_on_overhangs", "Extra perimeters on overhangs", "bool"], ["overhang_reverse", "Reverse on even", "bool"],
      ["overhang_reverse_internal_only", "Reverse only internal perimeters", "bool"], ["overhang_reverse_threshold", "Reverse threshold", "mm"],
    ],
  },
];
const STRENGTH = [
  { title: "Walls", rows: [["wall_loops", "Wall loops"], ["alternate_extra_wall", "Alternate extra wall", "bool"], ["detect_thin_wall", "Detect thin wall", "bool"]] },
  {
    title: "Top/bottom shells",
    rows: [
      ["top_surface_pattern", "Top surface pattern", "enum"], ["top_shell_layers", "Top shell layers"], ["top_shell_thickness", "Top shell thickness", "mm"],
      ["top_surface_density", "Top surface density", "%"], ["bottom_surface_pattern", "Bottom surface pattern", "enum"], ["bottom_shell_layers", "Bottom shell layers"],
      ["bottom_shell_thickness", "Bottom shell thickness", "mm"], ["bottom_surface_density", "Bottom surface density", "%"],
      ["internal_solid_infill_pattern", "Internal solid infill pattern", "enum"],
    ],
  },
  {
    title: "Infill",
    rows: [
      ["sparse_infill_density", "Sparse infill density", "%"], ["fill_multiline", "Fill Multiline"], ["sparse_infill_pattern", "Sparse infill pattern", "enum"],
      ["infill_direction", "Sparse infill direction", "°"], ["solid_infill_direction", "Solid infill direction", "°"],
      ["rotate_solid_infill_direction", "Rotate solid infill direction", "bool"], ["infill_anchor", "Length of sparse infill anchor", "mm"],
      ["infill_anchor_max", "Maximum length of sparse infill anchor", "mm"], ["filter_out_gap_fill", "Filter out tiny gaps", "mm"],
      ["gap_fill_target", "Apply gap fill", "enum"], ["sparse_infill_rotate_template", "Sparse infill rotation template"],
      ["solid_infill_rotate_template", "Solid infill rotation template"], ["gyroid_optimized", "Optimized gyroid", "bool"],
      ["infill_overhang_angle", "Infill overhang angle", "°"], ["lateral_lattice_angle_1", "Lateral lattice angle 1", "°"],
      ["lateral_lattice_angle_2", "Lateral lattice angle 2", "°"], ["infill_shift_step", "Infill shift step", "mm"],
      ["symmetric_infill_y_axis", "Symmetric infill Y axis", "bool"],
    ],
  },
  {
    title: "Locked Zag",
    rows: [
      ["skin_infill_density", "Skin infill density", "%"], ["skeleton_infill_density", "Skeleton infill density", "%"],
      ["infill_lock_depth", "Infill lock depth", "mm"], ["skin_infill_depth", "Skin infill depth", "mm"],
      ["skin_infill_line_width", "Skin line width", "mm"], ["skeleton_infill_line_width", "Skeleton line width", "mm"],
    ],
  },
  {
    title: "Advanced",
    rows: [
      ["infill_wall_overlap", "Infill/Wall overlap", "%"], ["top_bottom_infill_wall_overlap", "Top/Bottom solid infill/wall overlap", "%"],
      ["infill_combination", "Infill combination", "bool"], ["infill_combination_max_layer_height", "Infill combination - Max layer height", "mm"],
      ["detect_narrow_internal_solid_infill", "Detect narrow internal solid infill", "bool"], ["ensure_vertical_shell_thickness", "Ensure vertical shell thickness", "enum"],
      ["minimum_sparse_infill_area", "Minimum sparse infill threshold", "mm²"], ["align_infill_direction_to_model", "Align infill direction to model", "bool"],
      ["extra_solid_infills", "Insert solid layers"], ["elefant_foot_layers_density", "Elephant foot layers density", "%"],
    ],
  },
];
const SPEED = [
  {
    title: "First layer speed",
    rows: [
      ["initial_layer_speed", "Initial layer", "mm/s"], ["initial_layer_infill_speed", "Initial layer infill", "mm/s"],
      ["initial_layer_travel_speed", "Initial layer travel speed", "mm/s"], ["slow_down_layers", "Number of slow layers"],
    ],
  },
  {
    title: "Other layers speed",
    rows: [
      ["outer_wall_speed", "Outer wall", "mm/s"], ["inner_wall_speed", "Inner wall", "mm/s"], ["small_perimeter_speed", "Small perimeters", "mm/s"],
      ["small_perimeter_threshold", "Small perimeters threshold", "mm"], ["sparse_infill_speed", "Sparse infill", "mm/s"],
      ["internal_solid_infill_speed", "Internal solid infill", "mm/s"], ["top_surface_speed", "Top surface", "mm/s"], ["gap_infill_speed", "Gap infill", "mm/s"],
      ["ironing_speed", "Ironing speed", "mm/s"], ["support_speed", "Support", "mm/s"], ["support_interface_speed", "Support interface", "mm/s"],
    ],
  },
  {
    title: "Overhang speed",
    rows: [
      ["enable_overhang_speed", "Slow down for overhang", "bool"], ["slowdown_for_curled_perimeters", "Slow down for curled perimeters", "bool"],
      ["overhang_1_4_speed", "(10%, 25%)", "mm/s"], ["overhang_2_4_speed", "[25%, 50%)", "mm/s"], ["overhang_3_4_speed", "[50%, 75%)", "mm/s"],
      ["overhang_4_4_speed", "[75%, 100%)", "mm/s"], ["bridge_speed", "Bridge", "mm/s"], ["internal_bridge_speed", "Internal", "mm/s"],
    ],
  },
  { title: "Travel speed", rows: [["travel_speed", "Travel", "mm/s"], ["travel_speed_z", "Z travel", "mm/s"]] },
  {
    title: "Acceleration",
    rows: [
      ["default_acceleration", "Normal printing", "mm/s²"], ["outer_wall_acceleration", "Outer wall", "mm/s²"], ["inner_wall_acceleration", "Inner wall", "mm/s²"],
      ["bridge_acceleration", "Bridge", "mm/s²"], ["sparse_infill_acceleration", "Sparse infill", "mm/s²"],
      ["internal_solid_infill_acceleration", "Internal solid infill", "mm/s²"], ["initial_layer_acceleration", "Initial layer", "mm/s²"],
      ["top_surface_acceleration", "Top surface", "mm/s²"], ["travel_acceleration", "Travel", "mm/s²"],
      ["initial_layer_travel_acceleration", "Initial layer travel", "mm/s²"],
      ["accel_to_decel_enable", "Enable accel_to_decel", "bool"], ["accel_to_decel_factor", "accel_to_decel", "%"],
    ],
  },
  {
    title: "Jerk(XY)",
    rows: [
      ["default_jerk", "Default", "mm/s"], ["outer_wall_jerk", "Outer wall", "mm/s"], ["inner_wall_jerk", "Inner wall", "mm/s"], ["infill_jerk", "Infill", "mm/s"],
      ["top_surface_jerk", "Top surface", "mm/s"], ["initial_layer_jerk", "Initial layer", "mm/s"], ["travel_jerk", "Travel", "mm/s"],
      ["initial_layer_travel_jerk", "Initial layer travel", "mm/s"], ["default_junction_deviation", "Junction Deviation", "mm"],
    ],
  },
  {
    title: "Advanced",
    rows: [
      ["max_volumetric_extrusion_rate_slope", "Extrusion rate smoothing", "mm³/s²"],
      ["max_volumetric_extrusion_rate_slope_segment_length", "Smoothing segment length", "mm"],
      ["extrusion_rate_smoothing_external_perimeter_only", "Apply only on external features", "bool"],
    ],
  },
];
const SUPPORT = [
  {
    title: "Support",
    rows: [
      ["enable_support", "Enable support", "bool"], ["support_type", "Type", "enum"], ["support_style", "Style", "enum"],
      ["support_threshold_angle", "Threshold angle", "°"], ["support_threshold_overlap", "Threshold overlap", "%"],
      ["raft_first_layer_density", "Initial layer density", "%"], ["raft_first_layer_expansion", "Initial layer expansion", "mm"],
      ["support_on_build_plate_only", "On build plate only", "bool"], ["support_critical_regions_only", "Support critical regions only", "bool"],
      ["support_remove_small_overhang", "Remove small overhangs", "bool"], ["enforce_support_layers", "Enforce support for the first", "layers"],
    ],
  },
  { title: "Raft", rows: [["raft_layers", "Raft layers", "layers"], ["raft_contact_distance", "Raft contact Z distance", "mm"], ["raft_expansion", "Raft expansion", "mm"]] },
  {
    title: "Support filament",
    rows: [["support_filament", "Base"], ["support_interface_filament", "Interface"], ["support_interface_not_for_body", "Avoid interface filament for base", "bool"]],
  },
  {
    title: "Support ironing",
    rows: [
      ["support_ironing", "Ironing support interface", "bool"], ["support_ironing_pattern", "Ironing pattern", "enum"],
      ["support_ironing_flow", "Ironing flow", "%"], ["support_ironing_spacing", "Ironing line spacing", "mm"],
    ],
  },
  {
    title: "Advanced",
    rows: [
      ["support_top_z_distance", "Top Z distance", "mm"], ["support_bottom_z_distance", "Bottom Z distance", "mm"],
      ["support_base_pattern", "Base pattern", "enum"], ["support_base_pattern_spacing", "Base pattern spacing", "mm"],
      ["support_angle", "Pattern angle", "°"], ["support_interface_top_layers", "Top interface layers", "layers"],
      ["support_interface_bottom_layers", "Bottom interface layers", "layers"], ["support_interface_pattern", "Interface pattern", "enum"],
      ["support_interface_spacing", "Top interface spacing", "mm"], ["support_bottom_interface_spacing", "Bottom interface spacing", "mm"],
      ["support_expansion", "Normal support expansion", "mm"], ["support_object_xy_distance", "Support/object xy distance", "mm"],
      ["support_object_first_layer_gap", "Support/object first layer gap", "mm"], ["bridge_no_support", "Don't support bridges", "bool"],
      ["max_bridge_length", "Max bridge length", "mm"], ["independent_support_layer_height", "Independent support layer height", "bool"],
      ["support_interface_loop_pattern", "Interface loop pattern", "bool"], ["support_object_skip_flush", "Skip flush for support", "bool"],
    ],
  },
  {
    title: "Tree supports",
    rows: [
      ["tree_support_tip_diameter", "Tip Diameter", "mm"], ["tree_support_branch_distance", "Tree support branch distance", "mm"],
      ["tree_support_branch_diameter", "Tree support branch diameter", "mm"], ["tree_support_branch_angle", "Tree support branch angle", "°"],
      ["tree_support_branch_diameter_angle", "Branch Diameter Angle", "°"], ["tree_support_wall_count", "Support wall loops"],
      ["tree_support_angle_slow", "Preferred Branch Angle", "°"], ["tree_support_branch_angle_organic", "Tree support branch angle (organic)", "°"],
      ["tree_support_branch_diameter_organic", "Tree support branch diameter (organic)", "mm"],
      ["tree_support_branch_distance_organic", "Tree support branch distance (organic)", "mm"], ["tree_support_top_rate", "Branch Density", "%"],
      ["tree_support_auto_brim", "Auto brim width", "bool"], ["tree_support_brim_width", "Tree support brim width", "mm"],
    ],
  },
];
const MULTIMATERIAL = [
  {
    title: "Prime tower",
    rows: [
      ["enable_prime_tower", "Enable", "bool"], ["prime_tower_width", "Width", "mm"], ["prime_volume", "Prime volume", "mm³"],
      ["prime_tower_brim_width", "Brim width", "mm"], ["wipe_tower_rotation_angle", "Wipe tower rotation angle", "°"],
      ["wipe_tower_bridging", "Maximal bridging distance", "mm"], ["wipe_tower_cone_angle", "Stabilization cone apex angle", "°"],
      ["wipe_tower_extra_spacing", "Wipe tower purge lines spacing", "%"], ["wipe_tower_no_sparse_layers", "No sparse layers (beta)", "bool"],
      ["single_extruder_multi_material_priming", "Prime all printing extruders", "bool"], ["wipe_tower_type", "Wipe tower type", "enum"],
      ["wipe_tower_wall_type", "Wall type", "enum"], ["wipe_tower_extra_rib_length", "Extra rib length", "mm"], ["wipe_tower_rib_width", "Rib width", "mm"],
      ["wipe_tower_fillet_wall", "Fillet wall", "bool"], ["wipe_tower_extra_flow", "Extra flow for purge", "%"],
      ["wipe_tower_max_purge_speed", "Maximum wipe tower print speed", "mm/s"], ["prime_tower_infill_gap", "Infill gap", "%"],
      ["prime_tower_skip_points", "Skip points", "bool"], ["prime_tower_enable_framework", "Internal ribs", "bool"],
      ["wipe_tower_x", "Position X", "mm"], ["wipe_tower_y", "Position Y", "mm"],
    ],
  },
  {
    title: "Filament for Features",
    rows: [["wall_filament", "Walls"], ["sparse_infill_filament", "Infill"], ["solid_infill_filament", "Solid infill"], ["wipe_tower_filament", "Wipe tower"]],
  },
  {
    title: "Ooze prevention",
    rows: [["ooze_prevention", "Enable", "bool"], ["standby_temperature_delta", "Temperature variation", "°C"], ["preheat_time", "Preheat time", "s"], ["preheat_steps", "Preheat steps"]],
  },
  {
    title: "Flush options",
    rows: [
      ["flush_into_infill", "Flush into objects' infill", "bool"], ["flush_into_objects", "Flush into this object", "bool"],
      ["flush_into_support", "Flush into objects' support", "bool"], ["flush_multiplier", "Flush multiplier"], ["flush_volumes_matrix", "Flushing volumes"],
    ],
  },
  {
    title: "Advanced",
    rows: [
      ["interlocking_beam", "Use beam interlocking", "bool"], ["mmu_segmented_region_max_width", "Maximum width of a segmented region", "mm"],
      ["mmu_segmented_region_interlocking_depth", "Interlocking depth of a segmented region", "mm"], ["interlocking_beam_width", "Interlocking beam width", "mm"],
      ["interlocking_orientation", "Interlocking direction", "°"], ["interlocking_beam_layer_count", "Interlocking beam layers"],
      ["interlocking_depth", "Interlocking depth"], ["interlocking_boundary_avoidance", "Interlocking boundary avoidance"],
      ["interface_shells", "Interface shells", "bool"],
    ],
  },
];
const OTHERS = [
  {
    title: "Skirt",
    rows: [
      ["skirt_loops", "Skirt loops"], ["skirt_type", "Skirt type", "enum"], ["min_skirt_length", "Skirt minimum extrusion length", "mm"],
      ["skirt_distance", "Skirt distance", "mm"], ["skirt_start_angle", "Skirt start point", "°"], ["skirt_speed", "Skirt speed", "mm/s"],
      ["skirt_height", "Skirt height", "layers"], ["draft_shield", "Draft shield", "enum"], ["single_loop_draft_shield", "Single loop after first layer", "bool"],
    ],
  },
  {
    title: "Brim",
    rows: [
      ["brim_type", "Brim type", "enum"], ["brim_width", "Brim width", "mm"], ["brim_object_gap", "Brim-object gap", "mm"],
      ["brim_ears_max_angle", "Brim ears max angle", "°"], ["brim_ears_detection_length", "Brim ears detection radius", "mm"],
      ["brim_flow_ratio", "Brim flow ratio"], ["combine_brims", "Combine brims", "bool"], ["brim_use_efc_outline", "Brim follows compensated outline", "bool"],
    ],
  },
  {
    title: "Special mode",
    rows: [
      ["slicing_mode", "Slicing Mode", "enum"], ["print_sequence", "Print sequence", "enum"], ["print_order", "Intra-layer order", "enum"],
      ["spiral_mode", "Spiral vase", "bool"], ["spiral_mode_smooth", "Smooth Spiral", "bool"], ["spiral_mode_max_xy_smoothing", "Max XY Smoothing", "%"],
      ["timelapse_type", "Timelapse", "enum"],
    ],
  },
  {
    title: "Fuzzy Skin",
    rows: [
      ["fuzzy_skin", "Fuzzy Skin", "enum"], ["fuzzy_skin_mode", "Fuzzy skin generator mode", "enum"], ["fuzzy_skin_noise_type", "Fuzzy skin noise type", "enum"],
      ["fuzzy_skin_point_distance", "Fuzzy skin point distance", "mm"], ["fuzzy_skin_thickness", "Fuzzy skin thickness", "mm"],
      ["fuzzy_skin_first_layer", "Apply fuzzy skin to first layer", "bool"], ["fuzzy_skin_scale", "Fuzzy skin feature size", "mm"],
      ["fuzzy_skin_octaves", "Fuzzy Skin Noise Octaves"], ["fuzzy_skin_persistence", "Fuzzy skin noise persistence"],
      ["fuzzy_skin_ripples_per_layer", "Ripples per layer"], ["fuzzy_skin_ripple_offset", "Ripple offset", "%"],
      ["fuzzy_skin_layers_between_ripple_offset", "Layers between ripple offset", "layers"],
    ],
  },
  {
    title: "G-code output",
    rows: [
      ["reduce_infill_retraction", "Reduce infill retraction", "bool"], ["gcode_add_line_number", "Add line number", "bool"],
      ["gcode_comments", "Verbose G-code", "bool"], ["gcode_label_objects", "Label objects", "bool"], ["exclude_object", "Exclude objects", "bool"],
      ["filename_format", "Filename format"],
    ],
  },
  { title: "Post-processing Scripts", rows: [["post_process", "", "gcode"]] },
  { title: "Notes", rows: [["notes", "", "gcode"]] },
];

// ------------------------------------------------------------------ Filament
const plate = (key, name) => [[`${key}_initial_layer`, `${name}: Initial layer`, "°C"], [key, `${name}: Other layers`, "°C"]];
const FILAMENT = [
  {
    title: "Basic information",
    rows: [
      ["filament_type", "Type"], ["filament_vendor", "Vendor"], ["filament_colour", "Color", "color"], ["filament_soluble", "Soluble material", "bool"], ["filament_is_support", "Support material", "bool"],
      ["required_nozzle_HRC", "Required nozzle HRC"], ["default_filament_colour", "Default color", "color"], ["filament_diameter", "Diameter", "mm"],
      ["filament_adhesiveness_category", "Adhesiveness Category"], ["filament_density", "Density", "g/cm³"],
      ["filament_shrink", "Shrinkage (XY)", "%"], ["filament_shrinkage_compensation_z", "Shrinkage (Z)", "%"], ["filament_cost", "Price", "money/kg"],
      ["temperature_vitrification", "Softening temperature", "°C"], ["idle_temperature", "Idle temperature", "°C"],
    ],
  },
  {
    title: "Flow ratio and Pressure Advance",
    rows: [
      ["filament_flow_ratio", "Flow ratio"], ["enable_pressure_advance", "Enable pressure advance", "bool"], ["pressure_advance", "Pressure advance"],
      ["adaptive_pressure_advance", "Enable adaptive pressure advance (beta)", "bool"],
      ["adaptive_pressure_advance_overhangs", "Enable adaptive pressure advance for overhangs (beta)", "bool"],
      ["adaptive_pressure_advance_bridges", "Pressure advance for bridges"], ["adaptive_pressure_advance_model", "Adaptive pressure advance measurements (beta)", "gcode"],
    ],
  },
  {
    title: "Print chamber temperature",
    rows: [["chamber_temperature", "Chamber temperature", "°C"], ["activate_chamber_temp_control", "Activate temperature control", "bool"]],
  },
  {
    title: "Print temperature",
    rows: [
      ["nozzle_temperature_initial_layer", "Nozzle: Initial layer", "°C"], ["nozzle_temperature", "Nozzle: Other layers", "°C"],
      ["nozzle_temperature_range_low", "Recommended nozzle temperature: Min", "°C"], ["nozzle_temperature_range_high", "Recommended nozzle temperature: Max", "°C"],
    ],
  },
  {
    title: "Bed temperature",
    rows: [
      ...plate("supertack_plate_temp", "Cool Plate (SuperTack)"), ...plate("cool_plate_temp", "Cool Plate"),
      ...plate("textured_cool_plate_temp", "Textured Cool Plate"), ...plate("eng_plate_temp", "Engineering Plate"),
      ...plate("hot_plate_temp", "Smooth PEI Plate / High Temp Plate"), ...plate("textured_plate_temp", "Textured PEI Plate"),
    ],
  },
  {
    title: "Volumetric speed limitation",
    rows: [["filament_max_volumetric_speed", "Max volumetric speed", "mm³/s"], ["filament_adaptive_volumetric_speed", "Adaptive volumetric speed", "bool"]],
  },
];
const COOLING = [
  {
    title: "Cooling for specific layer",
    rows: [
      ["close_fan_the_first_x_layers", "No cooling for the first", "layers"], ["full_fan_speed_layer", "Full fan speed at layer"],
      ["first_x_layer_fan_speed", "Fan speed for the first layers", "%"],
    ],
  },
  {
    title: "Part cooling fan",
    rows: [
      ["fan_min_speed", "Min fan speed threshold: Fan speed", "%"], ["fan_cooling_layer_time", "Min fan speed threshold: Layer time", "s"],
      ["fan_max_speed", "Max fan speed threshold: Fan speed", "%"], ["slow_down_layer_time", "Max fan speed threshold: Layer time", "s"],
      ["reduce_fan_stop_start_freq", "Keep fan always on", "bool"], ["slow_down_for_layer_cooling", "Slow printing down for better layer cooling", "bool"],
      ["dont_slow_down_outer_wall", "Don't slow down outer walls", "bool"], ["slow_down_min_speed", "Min print speed", "mm/s"],
      ["enable_overhang_bridge_fan", "Force cooling for overhangs and bridges", "bool"], ["overhang_fan_threshold", "Overhang cooling activation threshold", "enum"],
      ["overhang_fan_speed", "Overhangs and external bridges fan speed", "%"], ["internal_bridge_fan_speed", "Internal bridges fan speed", "%"],
      ["support_material_interface_fan_speed", "Support interface fan speed", "%"], ["ironing_fan_speed", "Ironing fan speed", "%"],
    ],
  },
  {
    title: "Auxiliary part cooling fan",
    rows: [
      ["additional_cooling_fan_speed", "Fan speed", "%"], ["close_additional_fan_first_x_layers", "No auxiliary cooling for the first", "layers"],
      ["additional_fan_full_speed_layer", "Full auxiliary fan speed at layer"],
    ],
  },
  {
    title: "Exhaust fan",
    rows: [
      ["activate_air_filtration", "Activate air filtration", "bool"], ["activate_air_filtration_during_print", "During print", "bool"],
      ["during_print_exhaust_fan_speed", "During print: Fan speed", "%"], ["activate_air_filtration_on_completion", "Complete print", "bool"],
      ["complete_print_exhaust_fan_speed", "Complete print: Fan speed", "%"],
    ],
  },
];
const OVERRIDES = [
  {
    title: "Retraction",
    rows: [
      ["filament_retraction_length", "Length", "mm"], ["filament_z_hop", "Z-hop height", "mm"], ["filament_z_hop_types", "Z-hop type", "enum"],
      ["filament_retract_lift_above", "Only lift Z above", "mm"], ["filament_retract_lift_below", "Only lift Z below", "mm"],
      ["filament_retract_lift_enforce", "On surfaces", "enum"], ["filament_retraction_speed", "Retraction Speed", "mm/s"],
      ["filament_deretraction_speed", "Deretraction Speed", "mm/s"], ["filament_retract_restart_extra", "Extra length on restart", "mm"],
      ["filament_retraction_minimum_travel", "Travel distance threshold", "mm"], ["filament_retract_when_changing_layer", "Retract when change layer", "bool"],
      ["filament_wipe", "Wipe while retracting", "bool"], ["filament_wipe_distance", "Wipe distance", "mm"],
      ["filament_retract_before_wipe", "Retract amount before wipe", "%"], ["filament_long_retractions_when_cut", "Long retraction when cut (beta)", "bool"],
      ["filament_retraction_distances_when_cut", "Retraction distance when cut", "mm"],
    ],
  },
  {
    title: "Ironing",
    rows: [
      ["filament_ironing_flow", "Ironing flow", "%"], ["filament_ironing_spacing", "Ironing line spacing", "mm"],
      ["filament_ironing_inset", "Ironing inset", "mm"], ["filament_ironing_speed", "Ironing speed", "mm/s"],
    ],
  },
];
const FILAMENT_ADVANCED = [
  { title: "Filament start G-code", rows: [["filament_start_gcode", "", "gcode"]] },
  { title: "Filament end G-code", rows: [["filament_end_gcode", "", "gcode"]] },
];
const FILAMENT_MULTI = [
  { title: "Wipe tower parameters", rows: [["filament_minimal_purge_on_wipe_tower", "Minimal purge on wipe tower", "mm³"]] },
  {
    title: "Tool change parameters with single extruder MM printers",
    rows: [
      ["filament_loading_speed_start", "Loading speed at the start", "mm/s"], ["filament_loading_speed", "Loading speed", "mm/s"],
      ["filament_unloading_speed_start", "Unloading speed at the start", "mm/s"], ["filament_unloading_speed", "Unloading speed", "mm/s"],
      ["filament_toolchange_delay", "Delay after unloading", "s"], ["filament_cooling_moves", "Number of cooling moves"],
      ["filament_cooling_initial_speed", "Speed of the first cooling move", "mm/s"], ["filament_cooling_final_speed", "Speed of the last cooling move", "mm/s"],
      ["filament_stamping_loading_speed", "Stamping loading speed", "mm/s"], ["filament_stamping_distance", "Stamping distance", "mm"],
      ["filament_ramming_parameters", "Ramming parameters"],
    ],
  },
  {
    title: "Tool change parameters with multi extruder MM printers",
    rows: [
      ["filament_multitool_ramming", "Enable ramming for multi-tool setups", "bool"], ["filament_multitool_ramming_volume", "Multi-tool ramming volume", "mm³"],
      ["filament_multitool_ramming_flow", "Multi-tool ramming flow", "mm³/s"],
    ],
  },
];
const FILAMENT_DEPS = [
  {
    title: "Compatible printers",
    rows: [["compatible_printers", "Compatible printers"], ["compatible_printers_condition", "Compatible printers condition"]],
  },
  {
    title: "Compatible process profiles",
    rows: [["compatible_prints", "Compatible process profiles"], ["compatible_prints_condition", "Compatible process profiles condition"]],
  },
];

// ------------------------------------------------------------------ Printer
const BASIC = [
  {
    title: "Printable space",
    rows: [
      ["printable_area", "Printable area", "bed"], ["bed_exclude_area", "Excluded bed area"], ["bed_custom_texture", "Custom texture"],
      ["bed_custom_model", "Custom model"], ["best_object_pos", "Best object position"], ["z_offset", "Z offset", "mm"],
      ["preferred_orientation", "Preferred orientation", "°"], ["printable_height", "Printable height", "mm"],
      ["curr_bed_type", "Bed type"], ["default_bed_type", "Default bed type"],
    ],
  },
  {
    title: "Printer",
    rows: [
      ["printer_model", "Printer model"], ["printer_variant", "Variant"], ["printer_technology", "Printer technology"],
      ["extruder_type", "Extruder type"], ["nozzle_height", "Extruder height", "mm"], ["nozzle_volume_type", "Nozzle volume type"],
    ],
  },
  {
    title: "Advanced",
    rows: [
      ["printer_structure", "Printer structure", "enum"], ["gcode_flavor", "G-code flavor", "enum"], ["pellet_modded_printer", "Pellet Modded Printer", "bool"],
      ["bbl_use_printhost", "Use 3rd-party print host", "bool"], ["scan_first_layer", "Scan first layer", "bool"],
      ["disable_m73", "Disable set remaining print time", "bool"], ["thumbnails", "G-code thumbnails"], ["thumbnails_format", "Format of G-code thumbnails", "enum"],
      ["use_relative_e_distances", "Use relative E distances", "bool"], ["use_firmware_retraction", "Use firmware retraction", "bool"],
      ["time_cost", "Time cost", "money/h"],
    ],
  },
  {
    title: "Cooling Fan",
    rows: [["fan_speedup_time", "Fan speed-up time", "s"], ["fan_speedup_overhangs", "Only overhangs", "bool"], ["fan_kickstart", "Fan kick-start time", "s"]],
  },
  {
    title: "Extruder Clearance",
    rows: [
      ["extruder_clearance_radius", "Radius", "mm"], ["extruder_clearance_height_to_rod", "Height to rod", "mm"],
      ["extruder_clearance_height_to_lid", "Height to lid", "mm"],
    ],
  },
  {
    title: "Adaptive bed mesh",
    rows: [
      ["bed_mesh_min", "Bed mesh min"], ["bed_mesh_max", "Bed mesh max"], ["bed_mesh_probe_distance", "Probe point distance"],
      ["adaptive_bed_mesh_margin", "Mesh margin", "mm"],
    ],
  },
  {
    title: "Accessory",
    rows: [
      ["nozzle_type", "Nozzle type", "enum"], ["nozzle_hrc", "Nozzle HRC"], ["auxiliary_fan", "Auxiliary part cooling fan", "bool"],
      ["support_chamber_temp_control", "Support controlling chamber temperature", "bool"], ["support_air_filtration", "Support air filtration", "bool"],
    ],
  },
];
const MACHINE_GCODE = [
  { title: "Machine start G-code", rows: [["machine_start_gcode", "", "gcode"]] },
  { title: "Machine end G-code", rows: [["machine_end_gcode", "", "gcode"]] },
  { title: "Printing by object G-code", rows: [["printing_by_object_gcode", "", "gcode"]] },
  { title: "Before layer change G-code", rows: [["before_layer_change_gcode", "", "gcode"]] },
  { title: "Layer change G-code", rows: [["layer_change_gcode", "", "gcode"]] },
  { title: "Timelapse G-code", rows: [["time_lapse_gcode", "", "gcode"]] },
  { title: "Change filament G-code", rows: [["change_filament_gcode", "", "gcode"]] },
  { title: "Change extrusion role G-code", rows: [["change_extrusion_role_gcode", "", "gcode"]] },
  { title: "Pause G-code", rows: [["machine_pause_gcode", "", "gcode"]] },
  { title: "Template Custom G-code", rows: [["template_custom_gcode", "", "gcode"]] },
];
const PRINTER_MULTI = [
  {
    title: "Single extruder multi-material setup",
    rows: [
      ["single_extruder_multi_material", "Single Extruder Multi Material", "bool"], ["manual_filament_change", "Manual Filament Change", "bool"],
      ["purge_in_prime_tower", "Purge in prime tower", "bool"], ["enable_filament_ramming", "Enable filament ramming", "bool"],
    ],
  },
  {
    title: "Single extruder multi-material parameters",
    rows: [
      ["cooling_tube_retraction", "Cooling tube position", "mm"], ["cooling_tube_length", "Cooling tube length", "mm"],
      ["parking_pos_retraction", "Filament parking position", "mm"], ["extra_loading_move", "Extra loading distance", "mm"],
      ["high_current_on_filament_swap", "High extruder current on filament swap", "bool"],
    ],
  },
  {
    title: "Advanced",
    rows: [
      ["machine_load_filament_time", "Filament load time", "s"], ["machine_unload_filament_time", "Filament unload time", "s"],
      ["machine_tool_change_time", "Tool change time", "s"],
    ],
  },
];
const EXTRUDER = [
  { title: "Basic information", rows: [["nozzle_diameter", "Nozzle diameter", "mm"], ["nozzle_volume", "Nozzle volume", "mm³"]] },
  { title: "Layer height limits", rows: [["min_layer_height", "Min", "mm"], ["max_layer_height", "Max", "mm"]] },
  { title: "Position", rows: [["extruder_offset", "Extruder offset", "mm"]] },
  {
    title: "Retraction",
    rows: [
      ["retraction_length", "Length", "mm"], ["retract_restart_extra", "Extra length on restart", "mm"], ["retraction_speed", "Retraction Speed", "mm/s"],
      ["deretraction_speed", "Deretraction Speed", "mm/s"], ["retraction_minimum_travel", "Travel distance threshold", "mm"],
      ["retract_when_changing_layer", "Retract when change layer", "bool"], ["wipe", "Wipe while retracting", "bool"], ["wipe_distance", "Wipe Distance", "mm"],
      ["retract_before_wipe", "Retract amount before wipe", "%"], ["retract_on_top_layer", "Retract on top layer", "bool"],
      ["long_retractions_when_cut", "Long retraction when cut (beta)", "bool"], ["retraction_distances_when_cut", "Retraction distance when cut", "mm"],
    ],
  },
  {
    title: "Z-Hop",
    rows: [
      ["z_hop", "Z-hop height", "mm"], ["z_hop_types", "Z-hop type", "enum"], ["travel_slope", "Traveling angle", "°"],
      ["retract_lift_above", "Only lift Z above", "mm"], ["retract_lift_below", "Only lift Z below", "mm"], ["retract_lift_enforce", "On surfaces", "enum"],
    ],
  },
  {
    title: "Retraction when switching material",
    rows: [["retract_length_toolchange", "Length", "mm"], ["retract_restart_extra_toolchange", "Extra length on restart", "mm"]],
  },
  { title: "Preview", rows: [["extruder_colour", "Extruder Color", "color"]] },
];
const PER_EXTRUDER = new Set(EXTRUDER.flatMap((g) => g.rows.map((r) => r[0])));
// Speed, acceleration and jerk limits hold two values each, Normal and Stealth (silent) mode
const MOTION = [
  {
    title: "Advanced",
    rows: [
      ["emit_machine_limits_to_gcode", "Emit limits to G-code", "bool"], ["silent_mode", "Supports silent mode", "bool"],
      ["resonance_avoidance", "Resonance avoidance", "bool"], ["min_resonance_avoidance_speed", "Min resonance avoidance speed", "mm/s"],
      ["max_resonance_avoidance_speed", "Max resonance avoidance speed", "mm/s"],
    ],
  },
  {
    title: "Input shaping",
    rows: [
      ["input_shaping_emit", "Emit input shaping", "bool"], ["input_shaping_type", "Input shaper type", "enum"],
      ["input_shaping_freq_x", "Frequency X", "Hz"], ["input_shaping_freq_y", "Frequency Y", "Hz"],
      ["input_shaping_damp_x", "Damping X"], ["input_shaping_damp_y", "Damping Y"],
    ],
  },
  {
    title: "Speed limitation", limits: true,
    rows: [["machine_max_speed_x", "Maximum speed X", "mm/s"], ["machine_max_speed_y", "Maximum speed Y", "mm/s"], ["machine_max_speed_z", "Maximum speed Z", "mm/s"], ["machine_max_speed_e", "Maximum speed E", "mm/s"]],
  },
  {
    title: "Acceleration limitation", limits: true,
    rows: [
      ["machine_max_acceleration_x", "Maximum acceleration X", "mm/s²"], ["machine_max_acceleration_y", "Maximum acceleration Y", "mm/s²"],
      ["machine_max_acceleration_z", "Maximum acceleration Z", "mm/s²"], ["machine_max_acceleration_e", "Maximum acceleration E", "mm/s²"],
      ["machine_max_acceleration_extruding", "Maximum acceleration when extruding", "mm/s²"],
      ["machine_max_acceleration_retracting", "Maximum acceleration when retracting", "mm/s²"],
      ["machine_max_acceleration_travel", "Maximum acceleration for travel", "mm/s²"],
    ],
  },
  {
    title: "Jerk limitation", limits: true,
    rows: [
      ["machine_max_jerk_x", "Maximum jerk X", "mm/s"], ["machine_max_jerk_y", "Maximum jerk Y", "mm/s"], ["machine_max_jerk_z", "Maximum jerk Z", "mm/s"],
      ["machine_max_jerk_e", "Maximum jerk E", "mm/s"], ["machine_max_junction_deviation", "Maximum Junction Deviation", "mm"],
    ],
  },
  {
    title: "Minimum speed", limits: true,
    rows: [["machine_min_extruding_rate", "Minimum speed for extruding", "mm/s"], ["machine_min_travel_rate", "Minimum travel speed", "mm/s"]],
  },
];

// How Orca names the choices in its drop-downs
export const ORCA_CHOICES = {
  seam_position: { nearest: "Nearest", aligned: "Aligned", back: "Back", random: "Random" },
  seam_slope_type: { none: "None", external: "Contour", all: "Contour and hole" },
  wall_generator: { classic: "Classic", arachne: "Arachne" },
  wall_sequence: { "inner wall/outer wall": "Inner/Outer", "outer wall/inner wall": "Outer/Inner", "inner-outer-inner wall": "Inner/Outer/Inner" },
  wall_direction: { auto: "Auto", ccw: "Counter clockwise", cw: "Clockwise" },
  ironing_type: { "no ironing": "No ironing", top: "Top surfaces", topmost: "Topmost surface", solid: "All solid layer" },
  sparse_infill_pattern: {
    concentric: "Concentric", zigzag: "Rectilinear", grid: "Grid", line: "Line", cubic: "Cubic", triangles: "Triangles", tri_hexagon: "Tri-hexagon",
    gyroid: "Gyroid", honeycomb: "Honeycomb", adaptivecubic: "Adaptive Cubic", alignedrectilinear: "Aligned Rectilinear", "3dhoneycomb": "3D Honeycomb",
    hilbertcurve: "Hilbert Curve", archimedeanchords: "Archimedean Chords", octagramspiral: "Octagram Spiral", supportcubic: "Support Cubic",
    lightning: "Lightning", crosshatch: "Cross Hatch", quartercubic: "Quarter Cubic", monotonic: "Monotonic", monotonicline: "Monotonic line",
  },
  ensure_vertical_shell_thickness: { none: "None", ensure_critical_only: "Critical Only", ensure_moderate: "Moderate", ensure_all: "All" },
  gap_fill_target: { everywhere: "Everywhere", topbottom: "Top and bottom surfaces", nowhere: "Nowhere" },
  support_type: { "normal(auto)": "normal(auto)", "tree(auto)": "tree(auto)", "normal(manual)": "normal(manual)", "tree(manual)": "tree(manual)" },
  support_style: { default: "Default", grid: "Grid", snug: "Snug", tree_slim: "Tree Slim", tree_strong: "Tree Strong", tree_hybrid: "Tree Hybrid", tree_organic: "Organic" },
  brim_type: { auto_brim: "Auto", brim_ears: "Mouse ear", outer_only: "Outer brim only", inner_only: "Inner brim only", outer_and_inner: "Outer and inner brim", no_brim: "No-brim" },
  skirt_type: { combined: "Combined", perobject: "Per object" },
  draft_shield: { disabled: "Disabled", enabled: "Enabled" },
  print_sequence: { "by layer": "By layer", "by object": "By object" },
  print_order: { default: "Default", as_obj_list: "As object list" },
  timelapse_type: { "0": "Traditional", "1": "Smooth" },
  fuzzy_skin: { none: "None", external: "Contour", all: "Contour and hole", allwalls: "All walls" },
  slicing_mode: { regular: "Regular", even_odd: "Even-odd", close_holes: "Close holes" },
  gcode_flavor: { marlin: "Marlin(legacy)", marlin2: "Marlin 2", klipper: "Klipper", reprapfirmware: "RepRapFirmware" },
  printer_structure: { undefine: "Undefine", corexy: "CoreXY", i3: "I3", hbot: "Hbot", delta: "Delta" },
  z_hop_types: { "Auto Lift": "Auto Lift", "Normal Lift": "Normal Lift", "Slope Lift": "Slope Lift", "Spiral Lift": "Spiral Lift" },
  nozzle_type: { undefine: "Undefine", hardened_steel: "Hardened steel", stainless_steel: "Stainless steel", brass: "Brass" },
};
for (const k of ["top_surface_pattern", "bottom_surface_pattern", "internal_solid_infill_pattern", "support_base_pattern", "support_interface_pattern", "ironing_pattern", "support_ironing_pattern"]) {
  ORCA_CHOICES[k] = ORCA_CHOICES.sparse_infill_pattern;
}

// Which window a setting no page has a place for belongs in
const PRINTER_HINTS = ["machine_", "printer_", "printable_", "extruder_", "bed_", "retract", "z_hop", "nozzle_", "host_", "print_host", "thumbnails", "gcode_flavor", "bbl_", "fan_speedup", "fan_kickstart", "auxiliary_fan", "support_air", "support_chamber", "travel_slope", "wipe_distance", "deretraction", "use_relative", "use_firmware"];
const FILAMENT_HINTS = ["filament_", "temp", "fan_", "_fan", "cool", "chamber", "pressure_advance", "air_filtration", "exhaust", "slow_down", "full_fan", "compatible_prints", "required_nozzle"];
const windowOf = (k) => {
  const printerish = PRINTER_HINTS.some((h) => k.startsWith(h) || k.includes(h));
  if (k.startsWith("filament_") || k.startsWith("nozzle_temperature")) return "filament";
  if (FILAMENT_HINTS.some((h) => k.includes(h)) && !(printerish && !k.includes("temp"))) return "filament";
  return printerish ? "printer" : "process";
};

const otherPage = (settings, pages, belongs) => {
  const placed = placedKeys(pages);
  const rest = Object.keys(settings).filter((k) => !placed.has(k) && belongs(k) && !k.endsWith("_settings_id")).sort();
  return rest.length ? [{ id: "other", title: "Other", Icon: Puzzle, groups: [{ title: "More settings in this 3MF", rows: rest.map((k) => [k, keyLabel(k)]) }] }] : [];
};
const extruders = (settings) => Math.max(1, String(settings?.nozzle_diameter ?? "").split(/[;,]/).filter((s) => s !== "").length);

// A setting as an Orca page shows it: an Extruder page shows its own extruder's value
export function orcaValue(settings) {
  return (key, page) => {
    const raw = settings?.[key];
    return page?.extruder != null && PER_EXTRUDER.has(key) ? nth(raw, page.extruder) : raw;
  };
}

// The three windows, as OrcaSlicer shows them
export function orcaTabs(settings) {
  const process = [
    { id: "quality", title: "Quality", Icon: Layers, groups: QUALITY },
    { id: "strength", title: "Strength", Icon: Shield, groups: STRENGTH },
    { id: "speed", title: "Speed", Icon: Gauge, groups: SPEED },
    { id: "support", title: "Support", Icon: Waypoints, groups: SUPPORT },
    { id: "multi", title: "Multimaterial", Icon: Paintbrush, groups: MULTIMATERIAL },
    { id: "others", title: "Others", Icon: SlidersHorizontal, groups: OTHERS },
  ];
  const filament = [
    { id: "filament", title: "Filament", Icon: Thermometer, groups: FILAMENT },
    { id: "cooling", title: "Cooling", Icon: Fan, groups: COOLING },
    { id: "overrides", title: "Setting Overrides", Icon: SlidersHorizontal, groups: OVERRIDES },
    { id: "advanced", title: "Advanced", Icon: Wrench, groups: FILAMENT_ADVANCED },
    { id: "multi", title: "Multimaterial", Icon: Paintbrush, groups: FILAMENT_MULTI },
    { id: "deps", title: "Dependencies", Icon: Link2, groups: FILAMENT_DEPS },
    { id: "notes", title: "Notes", Icon: StickyNote, groups: [{ title: "Notes", rows: [["filament_notes", "", "gcode"]] }] },
  ];
  const printer = [
    { id: "basic", title: "Basic information", Icon: Printer, groups: BASIC },
    { id: "gcode", title: "Machine G-code", Icon: FileCode, groups: MACHINE_GCODE },
    { id: "multi", title: "Multimaterial", Icon: Box, groups: PRINTER_MULTI },
    ...Array.from({ length: extruders(settings) }, (_, i) => ({ id: `extruder${i}`, title: `Extruder ${i + 1}`, Icon: CircleDot, groups: EXTRUDER, extruder: i })),
    { id: "motion", title: "Motion ability", Icon: Cog, groups: MOTION },
    { id: "notes", title: "Notes", Icon: StickyNote, groups: [{ title: "Notes", rows: [["printer_notes", "", "gcode"]] }] },
  ];
  // the settings each window's pages above have no place for; placed anywhere counts, so none shows twice
  const all = [...process, ...filament, ...printer];
  process.push(...otherPage(settings, all, (k) => windowOf(k) === "process"));
  filament.push(...otherPage(settings, all, (k) => windowOf(k) === "filament"));
  printer.push(...otherPage(settings, all, (k) => windowOf(k) === "printer"));
  return [
    { id: "process", title: "Process", Icon: SquareStack, preset: settings.print_settings_id, pages: process },
    { id: "filament", title: "Filament", Icon: Wind, preset: settings.filament_settings_id, pages: filament },
    { id: "printer", title: "Printer", Icon: Printer, preset: settings.printer_settings_id, pages: printer },
  ];
}
