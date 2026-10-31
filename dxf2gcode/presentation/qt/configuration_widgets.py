"""Qt widget definitions for application and postprocessor settings."""

from collections import OrderedDict

from dxf2gcode.presentation.qt.qt_compat import QtCore
from dxf2gcode.domain.toolpath.leadmove import lead_mode_labels
from dxf2gcode.presentation.qt.configwindow import (
    CfgCheckBox,
    CfgComboBox,
    CfgDoubleSpinBox,
    CfgLineEdit,
    CfgListEdit,
    CfgSpinBox,
    CfgSubtitle,
    CfgTableCustomActions,
    CfgTableToolParameters,
    CfgTextEdit,
)


def build_application_config_widgets(config):
    """Build Qt controls for the current application configuration model."""
    tr = config.tr
    coordinate_unit = tr(" mm") if config.tool_units == "mm" else tr(" in")
    speed_unit = tr(" mm/min") if config.tool_units == "mm" else tr(" IPS")
    return OrderedDict([
        ("__section_title__", {
            "Tool_Parameters": tr("Tools table"),
            "Custom_Actions": tr("Custom actions"),
        }),
        ("Paths", OrderedDict([
            ("__section_title__", tr("Software config")),
            ("import_dir", CfgLineEdit(tr("By default look for DXF files in:"))),
            ("output_dir", CfgLineEdit(tr("By default export generated G-Code to:"))),
            ("project_dir", CfgLineEdit(tr("By default save Project files to:"))),
            ("autosave_path", CfgCheckBox(tr("Update paths with last used path: "))),
        ])),
        ("Filters", OrderedDict([
            ("__section_title__", tr("Software config")),
            ("__subtitle__", CfgSubtitle("pdftops")),
            ("pdftops_cmd", CfgLineEdit(tr("Location of executable:"))),
            ("pdftops_opt", CfgListEdit(tr("Command-line options:"), ",")),
            ("__subtitle2__", CfgSubtitle("pstoedit")),
            ("pstoedit_cmd", CfgLineEdit(tr("Location of executable:"))),
            ("pstoedit_opt", CfgListEdit(tr("Command-line options:"), ",")),
        ])),
        ("General", OrderedDict([
            ("__section_title__", tr("General settings")),
            ("mode3d", CfgCheckBox(tr("3D mode (requires OpenGL - restart needed)"))),
            ("show_disabled_paths", CfgCheckBox(tr("Display disabled paths (default)"))),
            ("live_update_export_route", CfgCheckBox(tr("Live update export route (default)"))),
            ("show_scale_bar", CfgCheckBox(tr("Show a scale bar in the canvas"))),
            ("expand_layers_on_load", CfgCheckBox(
                QtCore.QCoreApplication.translate(
                    "MyConfig", "Expand layers when loading a drawing"))),
            ("__subtitle2__", CfgSubtitle(tr("Milling"))),
            ("split_line_segments", CfgCheckBox(tr("Split line segments (default)"))),
            ("automatic_cutter_compensation", CfgCheckBox(tr("Automatic cutter compensation (default)"))),
            ("machine_type", CfgComboBox(tr("Machine type (default):"))),
            ("tool_units", CfgComboBox(tr("Configuration values use the unit (restart needed):"))),
            ("__subtitle3__", CfgSubtitle(tr("Output"))),
            ("write_to_stdout", CfgCheckBox(tr("Export the G-Code to stdout (instead of a file)"))),
        ])),
        ("Axis_letters", OrderedDict([
            ("__section_title__", tr("Machine config")),
            ("__subtitle__", CfgSubtitle(tr("Axes' identifiers"))),
            ("ax1_letter", CfgLineEdit(tr("First axis:"))),
            ("ax2_letter", CfgLineEdit(tr("Second axis:"))),
            ("ax3_letter", CfgLineEdit(tr("Third axis:"))),
        ])),
        ("Plane_Coordinates", OrderedDict([
            ("__section_title__", tr("Machine config")),
            ("__subtitle__", CfgSubtitle(tr("Start and end's coordinate and scaling standard multiplier"))),
            ("axis1_start_end", CfgDoubleSpinBox(tr("First axis start/end coordiante:"), coordinate_unit)),
            ("axis2_start_end", CfgDoubleSpinBox(tr("Second axis start/end coordinate:"), coordinate_unit)),
            ("std_scale", CfgDoubleSpinBox(tr("Scale first and second axis:"))),
        ])),
        ("Depth_Coordinates", OrderedDict([
            ("__section_title__", tr("Machine config")),
            ("__subtitle__", CfgSubtitle(tr("Third axis' defaults"))),
            ("axis3_retract", CfgDoubleSpinBox(tr("Retraction coordinate:"), coordinate_unit)),
            ("axis3_safe_margin", CfgDoubleSpinBox(tr("Safety margin:"), coordinate_unit)),
            ("axis3_start_mill_depth", CfgDoubleSpinBox(tr("Workpiece origin coordinate:"), coordinate_unit)),
            ("axis3_slice_depth", CfgDoubleSpinBox(tr("Slice depth:"), coordinate_unit)),
            ("axis3_mill_depth", CfgDoubleSpinBox(tr("Final mill depth:"), coordinate_unit)),
        ])),
        ("Feed_Rates", OrderedDict([
            ("__section_title__", tr("Machine config")),
            ("__subtitle__", CfgSubtitle(tr("G1 feed rates"))),
            ("f_g1_plane", CfgDoubleSpinBox(tr("First and second axis (2D plane):"), speed_unit)),
            ("f_g1_depth", CfgDoubleSpinBox(tr("Third axis:"), speed_unit)),
        ])),
        ("Cutter_Compensation", OrderedDict([
            ("__section_title__", tr("Output settings")),
            ("__subtitle__", CfgSubtitle(tr("Cutter compensation"))),
            ("done_by_machine", CfgCheckBox(tr("Cutter compensation is done by machine (check box if machine reconizes G41 and G42 commands / uncheck otherwise. This also disables pocket milling.)"))),
        ])),
        ("Pocketing", OrderedDict([
            ("__section_title__", tr("Output settings")),
            ("__subtitle__", CfgSubtitle(tr("Pocket milling"))),
            ("pocket_edge_clearance", CfgDoubleSpinBox(tr("Pocket edge clearance (distance between cutting edge and contour, as % of tool diameter):"), " %", 0, 100, 2)),
        ])),
        ("Drag_Knife_Options", OrderedDict([
            ("__section_title__", tr("Output settings")),
            ("__subtitle__", CfgSubtitle(tr("Drag Knife options"))),
            ("drag_angle", CfgDoubleSpinBox(tr('Retract to drag depth ("Third axis slice depth") if angle exceeds:'), "°")),
            ("drag_start_angle", CfgDoubleSpinBox(tr("Direction the knife points to when the cut starts (0 = positive X axis):"), "°")),
            ("ramp_in_length", CfgDoubleSpinBox(tr("Ramp in length (the knife is plunged gradually over this length):"), "", None, None, 3)),
        ])),
        ("Lead_In_Out", OrderedDict([
            ("__section_title__", tr("Output settings")),
            ("__subtitle__", CfgSubtitle(tr("Lead in / lead out"))),
            ("lead_in_mode", CfgComboBox(tr("Default lead in at the start of the contour:"), item_labels=lead_mode_labels())),
            ("lead_out_mode", CfgComboBox(tr("Default lead out at the end of the contour:"), item_labels=lead_mode_labels())),
            ("overcut_enabled", CfgCheckBox(tr("Overcut: continue the cut along the contour beyond the closing point (closed contours only) - the length is defined per tool in the tools table"))),
        ])),
        ("Route_Optimisation", OrderedDict([
            ("__section_title__", tr("Output settings")),
            ("__subtitle__", CfgSubtitle(tr("TSP optimizer"))),
            ("default_TSP", CfgCheckBox(tr("By default enable the TSP optimization for ordering shapes (TSP = Travelling Salesman Problem)"))),
            ("TSP_shape_order", CfgComboBox(tr("Optimizer behaviour:"))),
            ("mutation_rate", CfgDoubleSpinBox(tr("Mutation rate:"))),
            ("max_population", CfgSpinBox(tr("Max population:"))),
            ("max_iterations", CfgSpinBox(tr("Max iterations:"))),
            ("begin_art", CfgComboBox(tr("Starting point:"))),
        ])),
        ("Import_Parameters", OrderedDict([
            ("__section_title__", tr("Output settings")),
            ("point_tolerance", CfgDoubleSpinBox(tr("DXF default import point tolerance:"), "", None, None, 5)),
            ("spline_check", CfgSpinBox(tr("DXF import spline check:"))),
            ("fitting_tolerance", CfgDoubleSpinBox(tr("DXF default import fit tolerance:"), "", None, None, 5)),
            ("insert_at_block_layer", CfgCheckBox(tr("insert elements which are part of a block to layer where the block is inserted"))),
            ("exclude_ignore_layers", CfgCheckBox(QtCore.QCoreApplication.translate(
                "MyConfig", "Do not import IGNORE layers"))),
            ("exclude_layer_zero", CfgCheckBox(QtCore.QCoreApplication.translate(
                "MyConfig", "Do not import layer 0"))),
        ])),
        ("Layer_Options", OrderedDict([
            ("__section_title__", tr("Automatic tool config")),
            ("id_float_separator", CfgLineEdit(tr("Separator between identifier and value:"))),
            ("__subtitle__", CfgSubtitle(tr("Parameters' identifiers"))),
            ("mill_depth_identifiers", CfgListEdit(tr("Final mill depth:"), ",")),
            ("slice_depth_identifiers", CfgListEdit(tr("Infeed depth:"), ",")),
            ("start_mill_depth_identifiers", CfgListEdit(tr("Workpiece top:"), ",")),
            ("retract_identifiers", CfgListEdit(tr("Retraction area:"), ",")),
            ("safe_margin_identifiers", CfgListEdit(tr("Safety margin:"), ",")),
            ("f_g1_plane_identifiers", CfgListEdit(tr("G1 feed rate for first and second axis (2D plane):"), ",")),
            ("f_g1_depth_identifiers", CfgListEdit(tr("G1 feed rate for third axis:"), ",")),
            ("tool_nr_identifiers", CfgListEdit(tr("Tool number:"), ",")),
            ("tool_diameter_identifiers", CfgListEdit(tr("Tool diameter:"), ",")),
            ("spindle_speed_identifiers", CfgListEdit(tr("Spindle speed:"), ",")),
            ("start_radius_identifiers", CfgListEdit(tr("Start radius (cutter compensation, deprecated - use the lead radius instead):"), ",")),
            ("milling_offset_identifiers", CfgListEdit(tr("Additional offset (finishing allowance):"), ",")),
            ("lead_in_mode_identifiers", CfgListEdit(tr("Lead in mode (0 = start move, 1 = off, 2 = straight, 3 = radius, 4 = configuration default):"), ",")),
            ("lead_out_mode_identifiers", CfgListEdit(tr("Lead out mode (0 = off, 1 = straight, 2 = radius, 3 = start move, 4 = configuration default):"), ",")),
            ("lead_radius_identifiers", CfgListEdit(tr("Common lead in / lead out radius at the workpiece:"), ",")),
            ("lead_length_identifiers", CfgListEdit(tr("Common lead in / lead out length of the straight part:"), ",")),
            ("overcut_length_identifiers", CfgListEdit(tr("Overcut length:"), ",")),
        ])),
        ("Tool_Parameters", CfgTableToolParameters(tr("Define the tools here:"))),
        ("Custom_Actions", CfgTableCustomActions(tr("Define here custom GCODE that can be inserted anywhere in the program:"))),
        ("Logging", OrderedDict([
            ("__section_title__", tr("Software config")),
            ("logfile", CfgLineEdit(tr("File used for logging (restart needed):"))),
            ("console_loglevel", CfgComboBox(tr("On stderr console log messages with importance minimal to level (restart needed):"))),
            ("file_loglevel", CfgComboBox(tr("For log-file log messages with importance minimal to level (restart needed):"))),
            ("window_loglevel", CfgComboBox(tr("For message box log messages with importance minimal to level (restart needed):"))),
        ])),
    ])


def build_postprocessor_config_widgets(translate):
    """Build Qt controls for the current postprocessor profile schema."""
    tr = translate
    return OrderedDict([
        ("__section_title__", {"Custom_GCode": tr("Custom GCode")}),
        ("General", OrderedDict([
            ("__section_title__", tr("Software config")),
            ("__subtitle__", CfgSubtitle(tr("Output specifications"))),
            ("output_text", CfgLineEdit(tr("Output format description (should be unique):"))),
            ("output_format", CfgLineEdit(tr("Output file extension:"))),
            ("output_type", CfgComboBox(tr("Output type:"))),
            ("__subtitle2__", CfgSubtitle(tr("Output options"))),
            ("abs_export", CfgCheckBox(tr("Export absolute coordinates"))),
            ("cancel_cc_for_depth", CfgCheckBox(tr("Cancel cutter compensation at each slice"))),
            ("cc_outside_the_piece", CfgCheckBox(tr("Perform cutter compensation outside the piece"))),
            ("export_ccw_arcs_only", CfgCheckBox(tr("Export only counter clockwise arcs"))),
            ("max_arc_radius", CfgDoubleSpinBox(tr("Maximum arc radius:"))),
            ("export_arcs_as_lines", CfgCheckBox(tr("Export all arcs as line seg"))),
            ("repeat_drill_move", CfgCheckBox(tr("Repeat Drill move for slices (only use wit abs coordinates)"))),
            ("__subtitle3__", CfgSubtitle(tr("G-code constants"))),
            ("code_begin_units_mm", CfgLineEdit(tr("Units in millimeters:"))),
            ("code_begin_units_in", CfgLineEdit(tr("Units in inch:"))),
            ("code_begin_prog_abs", CfgLineEdit(tr("Absolute programming:"))),
            ("code_begin_prog_inc", CfgLineEdit(tr("Incremental programming:"))),
            ("code_begin", CfgTextEdit(tr("Startup:"))),
            ("code_end", CfgTextEdit(tr("End:"))),
        ])),
        ("Number_Format", OrderedDict([
            ("__section_title__", tr("Output formatting")),
            ("__subtitle__", CfgSubtitle(tr("Output formatting"))),
            ("win_line_endings", CfgCheckBox(tr("Windows line-endings"))),
            ("signed_values", CfgCheckBox(tr("Prepend numbers with the '+' sign for positive values"))),
            ("pre_decimals", CfgSpinBox(tr("Number of digits before the decimal separator:"))),
            ("pre_decimal_zero_padding", CfgCheckBox(tr("Padding with '0' digit before the decimal separator"))),
            ("post_decimals", CfgSpinBox(tr("Number of digits after the decimal separator:"))),
            ("post_decimal_zero_padding", CfgCheckBox(tr("Padding with '0' digit after the decimal separator"))),
            ("decimal_separator", CfgLineEdit(tr("Decimal separator:"))),
        ])),
        ("Line_Numbers", OrderedDict([
            ("__section_title__", tr("Output formatting")),
            ("__subtitle__", CfgSubtitle(tr("Line numbers"))),
            ("use_line_nrs", CfgCheckBox(tr("Export line numbers"))),
            ("line_nrs_begin", CfgSpinBox(tr("Line number starts at:"))),
            ("line_nrs_step", CfgSpinBox(tr("Line number step:"))),
        ])),
        ("Program", OrderedDict([
            ("__section_title__", tr("G-code codes")),
            ("tool_change", CfgLineEdit(tr("Tool change:"))),
            ("feed_change", CfgLineEdit(tr("Feed rate change:"))),
            ("rap_pos_plane", CfgLineEdit(tr("Rapid positioning for XY plane:"))),
            ("rap_pos_depth", CfgLineEdit(tr("Rapid positioning for Z plane:"))),
            ("lin_mov_plane", CfgLineEdit(tr("Linear feed move for XY plane:"))),
            ("lin_mov_depth", CfgLineEdit(tr("Linear feed move for Z plane:"))),
            ("lin_mov_drill", CfgLineEdit(tr("Linear feed move for drilling:"))),
            ("lin_ret_drill", CfgLineEdit(tr("Linear retract move during drilling:"))),
            ("arc_int_cw", CfgLineEdit(tr("Clockwise feed move:"))),
            ("arc_int_ccw", CfgLineEdit(tr("Counter clockwise feed move:"))),
            ("cutter_comp_off", CfgLineEdit(tr("Disable cutter compensation:"))),
            ("cutter_comp_left", CfgLineEdit(tr("Left cutter compensation:"))),
            ("cutter_comp_right", CfgLineEdit(tr("Right cutter compensation:"))),
            ("pre_shape_cut", CfgLineEdit(tr("Placed in front of any shape:"))),
            ("post_shape_cut", CfgLineEdit(tr("Placed after any shape:"))),
            ("comment", CfgLineEdit(tr("Comment for current shape:"))),
        ])),
        ("Custom_GCode", CfgTableCustomActions(tr("Define here custom GCODE that can be inserted anywhere in the program:"))),
    ])

