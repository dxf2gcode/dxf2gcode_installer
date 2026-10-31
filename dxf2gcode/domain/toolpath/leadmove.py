# -*- coding: utf-8 -*-

############################################################################
#
#   Copyright (C) 2026
#
#   This file is part of DXF2GCODE.
#
#   DXF2GCODE is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   DXF2GCODE is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with DXF2GCODE.  If not, see <http://www.gnu.org/licenses/>.
#
############################################################################

"""
Geometry of the lead in, the lead out and the overcut.

This module contains the geometry which is common to all tool types and
cutter compensation methods. It does not know anything about the G-Code, the
GUI or the export: it only calculates the geometries and validates them.

Three different radii have to be distinguished:

  * the radius at the workpiece (R_w): the radius which is really milled.
    This is the value the user configures.
  * the radius of the tool center path (R_m): the radius the tool center
    travels on.
  * the programmed radius (R_p): the radius which is written into the G-Code.
    It is only different from R_m if the machine compensates the tool radius
    (G41/G42), because then the machine offsets the programmed path.

The tool center path radius is always

    R_m = R_w - r_tool

because the cutter edge which faces the material sweeps the workpiece arc.
The programmed radius is

    R_p = R_w   if the machine compensates (G41/G42, nominal plane)
    R_p = R_m   if dxf2gcode compensates (tool center plane)

A workpiece radius which is smaller than the tool radius can not be milled
at all: the tool center path radius would become negative. The limit case
R_w == r_tool is geometrically possible (the tool center does not move, the
cutter sweeps a full circle), but it is neither usable with G41/G42 (the
compensation of an arc with the radius of the tool collapses to a point) nor
with the internal compensation (the arc degenerates to a point). It is
therefore reported as a warning.

The geometric parameters of the lead in and the lead out are common to both
directions: they are defined per tool (see the tools table) and they can be
overwritten per layer. There are only two of them:

  * the radius at the workpiece (R_w): it is used by all the methods which
    contain an arc.
  * the length of the straight part (L): it is used by all the methods which
    contain a straight line. For the lead in it is the length of the straight
    part of the lead in for the software compensation and for the machine
    compensation G41/G42 (the machine compensates the same programmed length).
    For G40 (no cutter compensation) the historical length of the tool center
    radius is kept, so that the G40 path does not change.

The method (which is selected independently for the lead in and for the lead
out) decides which of them is really used:

  * 'off'      : no geometry at all, neither the radius nor the length is
                 used.
  * 'straight' : a straight line of the length L (in both planes).
  * 'radius'   : a quarter arc of the radius R_w (R_m in the tool center
                 plane). The arc is preceded by the straight line which builds
                 up the cutter compensation. That straight line is NOT an
                 additional lead in segment: with G41/G42 it is the movement
                 the machine needs to build up the tool radius compensation
                 (the compensation can only be built up with a movement in the
                 XY plane); with the software compensation it is the radial
                 transition from the dive point to the start of the arc. Its
                 length is the configured L for the lead in (both
                 compensation methods), so that the straight lead in is
                 configurable; the G40 case keeps the historical tool center
                 radius.
                 The 'radius' method is only selectable for the lead out (where
                 the build up movement is not needed). For the lead in it is
                 the same as the 'startmove' method with the internal cutter
                 compensation (and with G40), so both are merged into the
                 'startmove' method.
  * 'startmove': a straight line of the length L and a quarter arc of the
                 radius R_w (R_m in the tool center plane). With G41/G42 the
                 machine offsets the programmed nominal path; with the software
                 compensation the tool center path is programmed directly. The
                 lead in is not generated for the drag knife.

The lead out does not need a build up: the cutter compensation is already
active at the end of the contour, so the 'radius' method of the lead out is
the quarter arc only.

The parameters which are not needed by the selected methods are not validated:
an unused radius must not prevent the selection of a straight movement.
"""


from __future__ import absolute_import
from __future__ import division

import logging
from copy import deepcopy
from math import atan2, cos, sin

import dxf2gcode.bootstrap.runtime_state as g

from dxf2gcode.domain.geometry.arcgeo import ArcGeo
from dxf2gcode.domain.geometry.breakgeo import BreakGeo
from dxf2gcode.domain.geometry.linegeo import LineGeo
from dxf2gcode.domain.geometry.point import Point

from dxf2gcode.presentation.qt.qt_compat import QtCore


logger = logging.getLogger("core.leadmove")

eps = 1e-9

# Modes of the lead in / lead out
LEAD_OFF = 'off'
LEAD_STRAIGHT = 'straight'
LEAD_RADIUS = 'radius'
# The start move of the program: a straight line and a quarter arc. It is only
# generated with G41/G42 - with the internal cutter compensation and for the
# drag knife there is no lead in.
LEAD_STARTMOVE = 'startmove'
# The layer uses the method which is configured in the configuration file
LEAD_DEFAULT = 'default'

# All the methods which can be selected for the lead in and for the lead out
LEAD_METHODS = [LEAD_OFF, LEAD_STRAIGHT, LEAD_RADIUS, LEAD_STARTMOVE]

# The modes of the lead in and the lead out in the order in which they can be
# selected with a layer name identifier (see the Layer_Options).
LEAD_MODES = [LEAD_STARTMOVE, LEAD_OFF, LEAD_STRAIGHT, LEAD_RADIUS,
              LEAD_DEFAULT]
LEAD_OUT_MODES = [LEAD_OFF, LEAD_STRAIGHT, LEAD_RADIUS, LEAD_STARTMOVE,
                  LEAD_DEFAULT]

# The plane the geometry is calculated in
SPACE_NOMINAL = 'nominal'
SPACE_TOOL_CENTER = 'tool_center'

# Status of a geometry calculation
OK = 'ok'
WARNING = 'warning'
ERROR = 'error'


def _tr(string_to_translate):
    """
    Translate a string using the QCoreApplication translation framework.
    The strings are marked with the translation context "LeadMove", so that
    the translation update tool finds them.
    """
    return str(QtCore.QCoreApplication.translate("LeadMove",
                                                 string_to_translate))


def lead_move_enabled(machine_type=None):
    """
    Whether the lead in, the lead out and the overcut may be used.

    They are not available for the lathe: the X axis of a lathe is the
    diameter, so the radii would have to be doubled and the movement
    kinematics are completely different. The lathe path is therefore not
    touched by these functions.
    @param machine_type: the machine type, the global configuration by default
    @return: True if the functions may be used
    """
    if machine_type is None:
        machine_type = getattr(getattr(g, 'config', None), 'machine_type',
                               'milling')
    return machine_type != 'lathe'


def lead_mode_labels():
    """
    The (translated) labels of the methods of the lead in and of the lead
    out. They are used by the configuration window and by the mill settings
    of the tree, so that both show the same names.
    @return: a dictionary {method: label}
    """
    return {LEAD_OFF: QtCore.QCoreApplication.translate("LeadMove", "None"),
            LEAD_STRAIGHT: QtCore.QCoreApplication.translate("LeadMove",
                                                             "Straight"),
            LEAD_RADIUS: QtCore.QCoreApplication.translate("LeadMove",
                                                            "Circle"),
            LEAD_STARTMOVE: QtCore.QCoreApplication.translate(
                "LeadMove", "Straight with circle")}


# The state of the overcut of a shape: the shape uses the standard of the
# configuration file, the overcut is switched off or the overcut is active.
OVERCUT_DEFAULT = 'default'
OVERCUT_OFF = 'off'
OVERCUT_ON = 'on'
OVERCUT_STATES = [OVERCUT_DEFAULT, OVERCUT_OFF, OVERCUT_ON]


def resolve_overcut(shape_state, global_enabled):
    """
    Whether the overcut is active for a shape.

    The overcut is a setting of the shape (like the method of the lead in and
    of the lead out): a shape can use the standard of the configuration file
    (the [Lead_In_Out] section), switch the overcut off or activate it. This
    function is the only place where this is decided: the shape, the preview
    in the canvas and the export all use it, so that the preview and the
    export always use the same values.

    @param shape_state: the state of the overcut of the shape: OVERCUT_DEFAULT
            (the standard of the configuration file), OVERCUT_OFF (no overcut)
            or OVERCUT_ON (the overcut is active). A bool is accepted as well,
            for the compatibility with the older project files.
    @param global_enabled: the standard of the configuration file: is the
            overcut active?
    @return: True if the overcut is active
    """
    if isinstance(shape_state, bool):
        # The project files of the previous versions stored the value of the
        # configuration file (a bool).
        return shape_state
    if shape_state == OVERCUT_ON:
        return True
    if shape_state == OVERCUT_OFF:
        return False
    return bool(global_enabled)


def get_overcut_enabled(layer, global_enabled=False):
    """
    Whether the overcut is active for the given layer.

    @param layer: the layer content
    @param global_enabled: the standard of the configuration file (used if
            the layer does not know the setting)
    @return: True if the overcut is active
    """
    getter = getattr(layer, 'get_overcut_enabled', None)
    if getter is not None:
        return getter()
    return resolve_overcut(getattr(layer, 'overcut_enabled', OVERCUT_DEFAULT),
                           global_enabled)


def mode_needs_radius(mode):
    """
    Whether the method needs the radius at the workpiece.
    @param mode: the method (LEAD_OFF, LEAD_STRAIGHT, LEAD_RADIUS or
                 LEAD_STARTMOVE)
    @return: True if the method contains an arc
    """
    return mode in (LEAD_RADIUS, LEAD_STARTMOVE)


def mode_needs_length(mode):
    """
    Whether the method needs the length of the straight part for the lead out.
    @param mode: the method (LEAD_OFF, LEAD_STRAIGHT, LEAD_RADIUS or
                 LEAD_STARTMOVE)
    @return: True if the method contains a straight line
    """
    return mode in (LEAD_STRAIGHT, LEAD_STARTMOVE)


def lead_in_needs_length(mode, compensated=True):
    """
    Whether the lead in needs the length of the straight part.

    With a cutter compensation (software or machine) the 'radius' lead in also
    has a straight part of the configured length (definition B), so the length
    is needed. With G40 (no cutter compensation) the 'radius' lead in uses the
    historical tool center radius and does not use the length.
    @param mode: the method of the lead in
    @param compensated: True if the contour is cut with a cutter compensation
                        (G41/G42 or the software compensation), False for G40
    @return: True if the lead in contains a straight line of the length
    """
    if mode in (LEAD_STRAIGHT, LEAD_STARTMOVE):
        return True
    return mode == LEAD_RADIUS and bool(compensated)


def resolve_mode(mode, default_mode):
    """
    The method which is really used: a layer which uses the configuration
    default (LEAD_DEFAULT) follows the global default value.
    @param mode: the method of the layer
    @param default_mode: the method of the configuration file
    @return: the method
    """
    if mode is None or mode == LEAD_DEFAULT:
        return default_mode
    return mode


def get_lead_in_mode(layer):
    """
    The method of the lead in which is really used for the given layer: a
    layer which uses the configuration default (LEAD_DEFAULT) follows the
    global default value of the configuration file.
    @param layer: the layer content
    @return: the method
    """
    getter = getattr(layer, 'get_lead_in_mode', None)
    if getter is not None:
        return getter()
    return resolve_mode(getattr(layer, 'lead_in_mode', LEAD_DEFAULT),
                        LEAD_STARTMOVE)


def get_lead_out_mode(layer):
    """
    The method of the lead out which is really used for the given layer: a
    layer which uses the configuration default (LEAD_DEFAULT) follows the
    global default value of the configuration file.
    @param layer: the layer content
    @return: the method
    """
    getter = getattr(layer, 'get_lead_out_mode', None)
    if getter is not None:
        return getter()
    return resolve_mode(getattr(layer, 'lead_out_mode', LEAD_DEFAULT),
                        LEAD_OFF)


def validate_lead_move(tool_diameter, lead_radius, lead_length,
                       lead_in_mode=LEAD_OFF, lead_out_mode=LEAD_OFF,
                       lead_in_compensated=True):
    """
    The central validation of the lead in / lead out parameters.

    It is used by the tool table of the configuration window, by the GUI and
    by the calculation of the toolpath, so that a combination which is
    accepted by the GUI is never rejected by the export (and the other way
    round).

    Only the parameters which are really needed by the selected methods are
    checked: an unused radius must not prevent the selection of a straight
    movement.

    The length is needed by the lead in for 'straight' and 'startmove' always,
    and for 'radius' when a cutter compensation is active (definition B: the
    radius lead in of the software and the machine compensation has a straight
    part of the configured length). With G40 the radius lead in uses the
    historical tool center radius, so ``lead_in_compensated`` is False there.
    The lead out never needs the length for 'radius'.

    @param tool_diameter: the diameter of the tool
    @param lead_radius: the common radius at the workpiece
    @param lead_length: the common length of the straight part
    @param lead_in_mode: the method of the lead in
    @param lead_out_mode: the method of the lead out
    @param lead_in_compensated: True if the lead in of the contour is cut with
            a cutter compensation (G41/G42 or the software compensation);
            False for G40
    @return: (ok, errors, warnings)
        ok: True if the parameters are valid
        errors: a list of (field, message) tuples, the field being the name
                of the invalid parameter ('tool_diameter', 'lead_radius' or
                'lead_length')
        warnings: a list of (field, message) tuples with the parameters which
                  are usable, but which are at the limit of what is possible
    """
    errors = []
    warnings = []

    try:
        tool_diameter = float(tool_diameter)
    except (TypeError, ValueError):
        tool_diameter = 0.0
    if tool_diameter <= 0:
        errors.append(('tool_diameter', QtCore.QCoreApplication.translate(
            "LeadMove", "The diameter of the tool must be greater than "
                        "zero.")))
        # Without a valid tool radius nothing else can be checked.
        return (False, errors, warnings)

    tool_radius = tool_diameter / 2.0

    modes = [lead_in_mode, lead_out_mode]

    if any(mode_needs_radius(mode) for mode in modes):
        try:
            lead_radius = float(lead_radius)
        except (TypeError, ValueError):
            lead_radius = 0.0
        if lead_radius <= 0:
            errors.append(('lead_radius', QtCore.QCoreApplication.translate(
                "LeadMove", "The radius of the lead in / lead out must be "
                            "greater than zero.")))
        elif lead_radius < tool_radius - eps:
            errors.append(('lead_radius', QtCore.QCoreApplication.translate(
                "LeadMove", "The radius at the workpiece (%.3f mm) is "
                            "smaller than the radius of the tool (%.3f mm) "
                            "- it can not be milled.")
                % (lead_radius, tool_radius)))
        elif abs(lead_radius - tool_radius) <= eps:
            # The limit case: it is geometrically possible, but the tool
            # center does not move while the arc is milled.
            warnings.append(('lead_radius', QtCore.QCoreApplication.translate(
                "LeadMove", "The radius at the workpiece (%.3f mm) equals "
                            "the radius of the tool: the tool center does "
                            "not move while the arc is milled. This limit "
                            "case is geometrically possible, but it is "
                            "difficult to machine.")
                % lead_radius))

    if (lead_in_needs_length(lead_in_mode, lead_in_compensated) or
            mode_needs_length(lead_out_mode)):
        try:
            lead_length = float(lead_length)
        except (TypeError, ValueError):
            lead_length = 0.0
        if lead_length <= 0:
            errors.append(('lead_length', QtCore.QCoreApplication.translate(
                "LeadMove", "The length of the lead in / lead out must be "
                            "greater than zero.")))

    return (not errors, errors, warnings)


def resolve_radius(workpiece_radius, tool_radius, space):
    """
    Convert the radius at the workpiece into the radius which has to be used
    in the given plane.

    @param workpiece_radius: the radius which shall be milled (R_w)
    @param tool_radius: the radius of the tool
    @param space: SPACE_NOMINAL (the machine compensates, G41/G42) or
                  SPACE_TOOL_CENTER (dxf2gcode compensates)
    @return: (radius, status, message)
        radius: the radius to use in the given plane
        status: OK, WARNING or ERROR
        message: an empty string if the status is OK
    """
    if tool_radius < 0:
        return 0.0, ERROR, QtCore.QCoreApplication.translate(
            "LeadMove", "The tool radius is negative - the lead in / lead "
                        "out can not be calculated.")

    if workpiece_radius <= 0:
        return 0.0, ERROR, QtCore.QCoreApplication.translate(
            "LeadMove", "The radius of the lead in / lead out has to be "
                        "greater than zero.")

    tool_center_radius = workpiece_radius - tool_radius
    if tool_center_radius < -eps:
        return 0.0, ERROR, QtCore.QCoreApplication.translate(
            "LeadMove", "The radius at the workpiece (%.3f mm) is smaller "
                        "than the tool radius (%.3f mm) - it can not be "
                        "milled.") % (workpiece_radius, tool_radius)

    if abs(tool_center_radius) <= eps:
        # The limit case: the tool center does not move while the arc is
        # milled, the cutter sweeps a full circle. It is geometrically
        # possible, but the machine compensation of an arc with the radius of
        # the tool collapses to a point and the internal compensation can not
        # build the (degenerate) arc at all.
        if space == SPACE_TOOL_CENTER:
            return 0.0, ERROR, QtCore.QCoreApplication.translate(
                "LeadMove", "The radius at the workpiece equals the tool "
                            "radius (%.3f mm): the tool center does not move "
                            "while the arc is milled, so the arc can not be "
                            "built with the internal cutter compensation."
                            % workpiece_radius)
        return workpiece_radius, WARNING, QtCore.QCoreApplication.translate(
            "LeadMove", "The radius at the workpiece equals the tool radius "
                        "(%.3f mm): the tool center does not move while the "
                        "arc is milled. This limit case is geometrically "
                        "possible, but the machine compensation of an arc "
                        "with the radius of the tool collapses to a point."
                        % workpiece_radius)

    if space == SPACE_NOMINAL:
        return workpiece_radius, OK, ""
    return tool_center_radius, OK, ""


def _normal(angle, side):
    """
    The normal vector of the given travel direction, scaled with the side.
    @param angle: the travel direction (rad)
    @param side: +1 = left of the travel direction, -1 = right of it
    @return: a Point
    """
    return Point(x=-sin(angle) * side, y=cos(angle) * side)


def _direction(angle, side):
    """
    The unit vector of the given travel direction.
    """
    return Point(x=cos(angle), y=sin(angle))


def _nominal_collapse_message(workpiece_radius, tool_radius):
    """
    The error message of the limit case R_w == r_tool in the nominal plane:
    the machine compensation of a nominal arc with the radius of the tool
    collapses to a point, so the arc can not be milled.

    @param workpiece_radius: the radius which shall be milled (R_w)
    @param tool_radius: the radius of the tool
    @return: the translated message
    """
    return QtCore.QCoreApplication.translate(
        "LeadMove", "The radius at the workpiece (%.3f mm) is not greater "
                    "than the radius of the tool (%.3f mm): the machine "
                    "compensation of the nominal arc collapses to a point, "
                    "so the arc can not be milled.") % (workpiece_radius,
                                                         tool_radius)


def build_start_move(end_point, angle, side, workpiece_radius, tool_radius,
                     length, space=SPACE_NOMINAL):
    """
    The start move of the program: a straight line and a quarter arc.

    This is the G41/G42 lead in of the program (it is used with the machine
    cutter compensation only).

    In the nominal plane the programmed path is compensated by the machine
    (G41/G42 is active while the start move is cut). The straight line then
    approaches the start of the quarter arc radially (it is tangent to the arc
    there) and its length is the common length; the arc itself is nominal, so
    the machine offsets it by the tool radius. In the tool center plane the
    programmed path is already the offset tool center path: the straight line
    continues the travel direction (tangentially) before the arc.

    @param end_point: the point where the start move ends (the contour start
            in the programmed plane)
    @param angle: the travel direction at the end point (rad)
    @param side: +1 = the arc curves to the left of the travel direction
    @param workpiece_radius: the radius which shall be milled (R_w)
    @param tool_radius: the radius of the tool
    @param length: the length of the straight part of the start move
    @param space: SPACE_NOMINAL (the machine compensates the programmed
            nominal path) or SPACE_TOOL_CENTER (the programmed path is already
            the tool center path, offset by the tool radius)
    @return: (geos, status, message)
    """
    radius, status, message = resolve_radius(workpiece_radius, tool_radius,
                                              space)
    if status == ERROR:
        return [], ERROR, message
    if length <= 0:
        return [], ERROR, QtCore.QCoreApplication.translate(
            "LeadMove", "The length of the lead in has to be greater than "
                        "zero.")
    if space == SPACE_NOMINAL and radius - tool_radius <= eps:
        # The machine compensates the nominal arc: the tool center path radius
        # would be zero and the arc would collapse to a point.
        return [], ERROR, _nominal_collapse_message(workpiece_radius,
                                                     tool_radius)
    tangent = _direction(angle, side)
    normal = _normal(angle, side)
    # Center of the starting radius
    center = end_point + normal * radius
    # Start point of the radius
    arc_start = center - tangent * radius
    if space == SPACE_NOMINAL:
        # The programmed (nominal) path is compensated by the machine: the
        # straight line approaches the arc radially (tangential to the arc at
        # its start) and its length is the common length.
        dive_point = arc_start + normal * length
    else:
        # The programmed path is already the tool center path (the offset is
        # applied by dxf2gcode): the straight line continues the travel
        # direction (tangentially) before the arc.
        dive_point = arc_start + tangent * length

    geos = [LineGeo(dive_point, arc_start),
            ArcGeo(Ps=arc_start, Pe=end_point, O=center, r=radius,
                   direction=1 if side > 0 else 0)]
    return geos, status, message


def build_lead_in(end_point, angle, side, workpiece_radius, tool_radius,
                  space, mode, length=0.0, use_lead_length=False):
    """
    Build the geometry of a lead in.

    The lead in ends at the given point with the given travel direction. With
    LEAD_RADIUS/LEAD_STARTMOVE a quarter arc is generated which is tangent to
    the contour at the end point. The arc is preceded by a straight line which
    approaches it radially (it is tangent to the arc at its start).

    The length of that straight part is the configured length L
    (`lead_length`) for the software compensation and for the machine
    compensation G41/G42 (see `use_lead_length`): the machine compensation
    programs the nominal line with the length L and the machine offsets it;
    the software compensation programs the tool center path directly with the
    same straight length. The historical tool center radius (R_w - r_tool) is
    kept for G40 (no cutter compensation), so that the G40 path does not
    change.

    With the machine compensation the lead in is programmed in the nominal
    plane (G41/G42 is active while it is cut): the quarter arc is nominal and
    the machine offsets it by the tool radius. With the internal compensation
    the programmed path is already the tool center path.

    With LEAD_STRAIGHT the contour is simply extended backwards along its
    tangent, so the tool enters the material tangentially (the length of the
    straight line is the common length, in both planes).

    @param end_point: the point where the lead in ends (the contour start)
    @param angle: the travel direction at the end point (rad)
    @param side: +1 = the arc curves to the left of the travel direction
    @param workpiece_radius: the radius which shall be milled (R_w)
    @param tool_radius: the radius of the tool
    @param space: SPACE_NOMINAL (the machine compensates the programmed
            nominal lead in) or SPACE_TOOL_CENTER (the lead in is already the
            offset tool center path)
    @param mode: LEAD_RADIUS, LEAD_STRAIGHT or LEAD_STARTMOVE
    @param length: the length of the straight part of the lead in
    @param use_lead_length: use `length` for the straight part of the tool
            center path (software compensation); False keeps the historical
            tool center radius (G40)
    @return: (geos, status, message)
    """
    if mode == LEAD_STRAIGHT:
        # The contour is extended backwards: the tool enters the material
        # tangentially and without a corner.
        if length <= 0:
            return [], ERROR, QtCore.QCoreApplication.translate(
                "LeadMove", "The length of the lead in has to be greater "
                            "than zero.")
        direction = _direction(angle, side)
        dive = end_point - direction * length
        return [LineGeo(dive, end_point)], OK, ""

    if mode in (LEAD_RADIUS, LEAD_STARTMOVE):
        # The circle / start move of the program (a straight line and a
        # quarter arc) is the lead in of the machine compensation: it is
        # programmed in the nominal plane and the machine offsets it. With the
        # internal cutter compensation the start move is the same as the
        # 'circle' lead in (a radial line and a quarter arc of the already
        # offset tool center path).
        #
        # The 'radius' and the 'startmove' methods are merged: in the tool
        # center plane (the internal cutter compensation and G40) both reduce
        # to a radial line and a quarter arc of the already offset tool center
        # path, so they can not be distinguished any more. The 'radius' method
        # is only selectable for the lead out (where the build up is not
        # needed), so it is mapped to the 'startmove' here.
        if space == SPACE_NOMINAL:
            return build_start_move(end_point, angle, side, workpiece_radius,
                                    tool_radius, length, space)
        mode = LEAD_STARTMOVE

    radius, status, message = resolve_radius(workpiece_radius, tool_radius,
                                              space)
    if status == ERROR:
        return [], ERROR, message
    # The nominal plane returned above (build_start_move); here the radius is
    # the radius of the tool center path R_m = R_w - r_tool.
    if use_lead_length:
        # Definition B: the configured lead length is the straight part of the
        # lead in for the software compensation too (the machine compensation
        # programs the same straight length in the nominal plane).
        if length <= 0:
            return [], ERROR, QtCore.QCoreApplication.translate(
                "LeadMove", "The length of the lead in has to be greater "
                            "than zero.")
        build_up_length = length
    else:
        # G40 (no cutter compensation): keep the historical tool center radius
        # as the build up length so that the G40 path does not change.
        build_up_length = radius

    if radius <= 0:
        return [], ERROR, QtCore.QCoreApplication.translate(
            "LeadMove", "The lead in radius is too small to be calculated.")

    tangent = _direction(angle, side)
    normal = _normal(angle, side)

    # Start point of the arc (the nominal contour start offset by the radius).
    center = end_point + normal * radius
    arc_start = center - tangent * radius
    # The dive point: radially in front of the start of the arc, so that the
    # straight line is tangent to the arc and the tool enters without a kink.
    dive_point = arc_start + normal * build_up_length

    geos = [LineGeo(dive_point, arc_start),
            ArcGeo(Ps=arc_start, Pe=end_point, O=center,
                   r=radius, direction=1 if side > 0 else 0)]
    return geos, status, message


def machine_g40_approach(nominal_geos, side, tool_radius, length):
    """
    The G40 approach line of a machine compensated lead in.

    With the machine cutter compensation (G41/G42) the lead in is programmed in
    the nominal plane and the machine builds the tool radius offset while it is
    cut. Before G41/G42 is switched on (G40) the compensation is not active, so
    dxf2gcode itself has to place the tool center beside the nominal lead in:
    the straight line which starts the nominal lead in is offset by the tool
    radius to the side the machine will compensate to, and its start (the dive
    point) is placed on that offset line.

    The line is parallel to the first (straight) geometry of the nominal lead
    in, so the tool center moves beside it while G40 is active and the machine
    can take over the offset at the end of the line without a lateral jump.

    @param nominal_geos: the geometries of the nominal lead in (the first one
            has to be the straight line)
    @param side: +1 = G41 (compensate to the left of the travel direction),
            -1 = G42 (to the right)
    @param tool_radius: the radius of the tool
    @param length: the length of the approach line (from the dive point to the
            nominal lead in start, measured along the line)
    @return: the LineGeo or None if it can not be built
    """
    if not nominal_geos or length <= 0 or tool_radius <= 0:
        return None
    first = nominal_geos[0]
    if not hasattr(first, 'Ps') or not hasattr(first, 'Pe'):
        return None
    line_length = first.Ps.distance(first.Pe)
    if line_length <= eps:
        return None
    direction = Point((first.Pe.x - first.Ps.x) / line_length,
                      (first.Pe.y - first.Ps.y) / line_length)
    # The side the machine compensates to (left for G41, right for G42).
    if side > 0:
        offset_dir = Point(-direction.y, direction.x)
    else:
        offset_dir = Point(direction.y, -direction.x)
    # The end of the approach line is the offset position of the start of the
    # nominal lead in line: there the machine takes over the compensation.
    approach_end = first.Ps + offset_dir * tool_radius
    dive = approach_end - direction * length
    return LineGeo(dive, approach_end)


def build_lead_out(end_point, angle, side, workpiece_radius, tool_radius,
                   space, mode, length=0.0):
    """
    Build the geometry of a lead out.

    The lead out starts at the given point with the given travel direction and
    leaves the contour. With LEAD_RADIUS a quarter arc is generated which
    leaves the contour tangentially, with LEAD_STRAIGHT the cut is continued
    along the tangent of the contour. With LEAD_STARTMOVE the cut is
    continued along the tangent of the contour (over the given length) and
    then it leaves the contour with a quarter arc.

    @param end_point: the point where the lead out starts (the contour end)
    @param angle: the travel direction at the end point (rad)
    @param side: +1 = the arc curves to the left of the travel direction
    @param workpiece_radius: the radius which shall be milled (R_w)
    @param tool_radius: the radius of the tool
    @param space: SPACE_NOMINAL or SPACE_TOOL_CENTER
    @param mode: LEAD_RADIUS, LEAD_STRAIGHT or LEAD_STARTMOVE
    @param length: the length of the straight part of the lead out
    @return: (geos, status, message)
    """
    if mode == LEAD_STRAIGHT:
        if length <= 0:
            return [], ERROR, QtCore.QCoreApplication.translate(
                "LeadMove", "The length of the lead out has to be greater "
                            "than zero.")
        direction = _direction(angle, side)
        return [LineGeo(end_point, end_point + direction * length)], OK, ""

    radius, status, message = resolve_radius(workpiece_radius, tool_radius,
                                              space)
    if status == ERROR:
        return [], ERROR, message

    tangent = _direction(angle, side)
    normal = _normal(angle, side)

    geos = []
    if mode == LEAD_STARTMOVE:
        # The straight line which continues the cut, followed by the quarter
        # arc which leaves the contour.
        if length <= 0:
            return [], ERROR, QtCore.QCoreApplication.translate(
                "LeadMove", "The length of the lead out has to be greater "
                            "than zero.")
        arc_start = end_point + tangent * length
        geos.append(LineGeo(end_point, arc_start))
    else:
        arc_start = end_point

    center = arc_start + normal * radius
    arc_end = center + tangent * radius

    geos.append(ArcGeo(Ps=arc_start, Pe=arc_end, O=center, r=radius,
                        direction=1 if side > 0 else 0))
    return geos, status, message


def cut_length(geo):
    """
    The length of a geometry which is really cut. A BreakGeo is a Z hop over
    a tab: it does not remove any material and must not be counted.
    @param geo: the geometry
    @return: the cut length
    """
    if isinstance(geo, BreakGeo):
        return 0.0
    return getattr(geo, "length", 0.0)


def chain_cut_length(geos):
    """
    The total length of the really cut geometry of a chain.
    @param geos: the chain
    @return: the cut length
    """
    return sum(cut_length(geo) for geo in geos)


def _partial_line(geo, length):
    """
    The first part of a line with the given length.
    @param geo: the LineGeo
    @param length: the wanted length
    @return: a new LineGeo
    """
    total = geo.length
    if total <= 0:
        return None
    factor = min(1.0, length / total)
    end = geo.Ps + (geo.Pe - geo.Ps) * factor
    return LineGeo(geo.Ps, end)


def _partial_arc(geo, length):
    """
    The first part of an arc with the given length.
    @param geo: the ArcGeo
    @param length: the wanted length
    @return: a new ArcGeo
    """
    total = geo.length
    if total <= 0:
        return None
    factor = min(1.0, length / total)
    angle = geo.s_ang + geo.ext * factor
    end = geo.O.get_arc_point(angle, geo.r)
    return ArcGeo(Ps=geo.Ps, Pe=end, O=geo.O, r=geo.r, s_ang=geo.s_ang,
                  direction=1 if geo.ext > 0 else 0)


def build_overcut(geos, length):
    """
    Build the overcut of a closed contour.

    The overcut continues the toolpath along the existing contour beyond the
    closing point: the beginning of the contour is repeated until the wanted
    length is reached. No new geometry outside of the contour is created and
    the original contour is not modified.

    @param geos: the chain of the contour (the exported pass geometry)
    @param length: the length of the overcut, measured along the really cut
                   geometry (BreakGeo Z hops are not counted)
    @return: (geos, status, message)
    """
    if length <= 0:
        return [], ERROR, QtCore.QCoreApplication.translate(
            "LeadMove", "The overcut length has to be greater than zero.")

    total = chain_cut_length(geos)
    if total <= 0:
        return [], ERROR, QtCore.QCoreApplication.translate(
            "LeadMove", "The contour does not contain any geometry which "
                        "could be overcut.")

    if length > total + eps:
        return [], ERROR, QtCore.QCoreApplication.translate(
            "LeadMove", "The overcut length (%.3f mm) is longer than the "
                        "contour (%.3f mm).") % (length, total)

    overcut = []
    remaining = length
    for geo in geos:
        if remaining <= eps:
            break
        if isinstance(geo, BreakGeo):
            # A tab: the tool hops over it, it is not cut. The hop is
            # repeated together with the contour, so the tab is not cut
            # either.
            overcut.append(deepcopy(geo))
            continue
        geo_length = cut_length(geo)
        if geo_length <= eps:
            continue
        if remaining >= geo_length - eps:
            overcut.append(deepcopy(geo))
            remaining -= geo_length
        else:
            if isinstance(geo, LineGeo):
                part = _partial_line(geo, remaining)
            elif isinstance(geo, ArcGeo):
                part = _partial_arc(geo, remaining)
            else:
                part = None
            if part is None:
                return [], ERROR, QtCore.QCoreApplication.translate(
                    "LeadMove", "The overcut can not be built from this "
                                "contour geometry.")
            overcut.append(part)
            remaining = 0.0
            break

    if not overcut:
        return [], ERROR, QtCore.QCoreApplication.translate(
            "LeadMove", "The overcut could not be calculated.")

    return overcut, OK, ""


def chain_end_point(geos):
    """
    The end point of a chain: the end point of the last geometry which is
    really cut (a BreakGeo is only a Z hop over a tab).
    @param geos: the chain
    @return: the end point or None if it can not be determined
    """
    for geo in reversed(list(geos)):
        if isinstance(geo, BreakGeo):
            continue
        return getattr(geo, "Pe", None)
    return None


def reverse_chain(geos):
    """
    A copy of the chain in the opposite direction (the same operation as
    Shape.reverse() without changing the direction of the shape itself).

    It is used for the preview of the exit geometry of the open contours:
    they are milled in alternating directions, so the last pass can be the
    mirrored one.

    @param geos: the chain
    @return: a new list with the reversed geometries
    """
    reversed_geos = deepcopy(list(geos))
    reversed_geos.reverse()
    for geo in reversed_geos:
        try:
            geo.reverse()
        except AttributeError:
            pass
    return reversed_geos


def build_exit_geometries(geos, side, space, tool_radius, lead_out_mode,
                          lead_radius, overcut_enabled, overcut_length,
                          closed=False, lead_length=0.0):
    """
    The geometry of the lead out and the overcut: the movements which are
    written at the end of the last pass.

    The overcut continues the cut along the existing contour beyond the
    closing point and is written first, the lead out starts at the end of the
    overcut and is written after it.

    The overcut is only possible for closed contours: for an open contour it is
    silently ignored (it is not an error - the lead out is still generated).

    This function is used by the export and by the preview in the canvas, so
    that both show the same geometry.

    @param geos: the chain of the last pass
    @param side: +1 = the arc curves to the left of the travel direction
    @param space: SPACE_NOMINAL or SPACE_TOOL_CENTER
    @param tool_radius: the radius of the tool
    @param lead_out_mode: LEAD_OFF, LEAD_STRAIGHT, LEAD_RADIUS or
                          LEAD_STARTMOVE
    @param lead_radius: the common radius at the workpiece
    @param overcut_enabled: whether the overcut is active
    @param overcut_length: the length of the overcut
    @param closed: True if the contour is closed (the overcut is only
            possible for closed contours)
    @param lead_length: the length of the straight part of the lead out
    @return: (geos, status, message)
    """
    exit_geos = []

    overcut_geos = []
    if overcut_enabled and closed:
        overcut_geos, status, message = build_overcut(geos, overcut_length)
        if status == ERROR:
            return [], ERROR, message
        exit_geos += overcut_geos

    if lead_out_mode != LEAD_OFF:
        # The lead out starts at the end of the overcut (if the overcut is
        # used) and leaves the contour from there.
        lead_out_chain = overcut_geos if overcut_enabled else geos
        start_point = chain_end_point(lead_out_chain)
        angle = chain_direction(lead_out_chain)
        if start_point is None or angle is None:
            return [], ERROR, QtCore.QCoreApplication.translate(
                "LeadMove", "The lead out can not be calculated.")
        lead_out_geos, status, message = build_lead_out(
            start_point, angle, side, lead_radius, tool_radius, space,
            lead_out_mode, length=lead_length)
        if status == ERROR:
            return [], ERROR, message
        exit_geos += lead_out_geos

    return exit_geos, OK, ""


def _geo_travel_direction(geo, at_start):
    """
    The travel direction (rad) of a geometry at its start or at its end.

    For a line this is the direction of the line. For an arc it is the tangent
    at the wanted point - NOT the angle of the point on the arc: the tangent
    is perpendicular to the radius, so the direction of a quarter arc changes
    by 90 degrees between its start and its end.

    @param geo: the geometry (LineGeo or ArcGeo)
    @param at_start: True for the direction at the start point, False for the
            direction at the end point
    @return: the angle (rad) or None if it can not be determined
    """
    if isinstance(geo, LineGeo):
        if geo.length <= eps:
            return None
        return geo.Ps.norm_angle(geo.Pe)
    if isinstance(geo, ArcGeo):
        if abs(geo.ext) <= eps:
            return None
        _, direction = geo.get_start_end_points(at_start, False)
        return atan2(direction.y, direction.x)
    return None


def chain_direction(geos):
    """
    The travel direction at the end of a chain (the direction of the last
    geometry at its end point).
    @param geos: the chain
    @return: the angle (rad) or None if it can not be determined
    """
    for geo in reversed(list(geos)):
        if isinstance(geo, BreakGeo):
            continue
        direction = _geo_travel_direction(geo, at_start=False)
        if direction is not None:
            return direction
    return None
