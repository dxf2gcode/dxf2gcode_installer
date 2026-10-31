# -*- coding: utf-8 -*-

############################################################################
#
#   Copyright (C) 2008-2015
#    Christian KohlÃ¶ffel
#    Vinzenz Schulz
#    Jean-Paul Schouwstra
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

from __future__ import absolute_import
from __future__ import division

from math import sin, cos, pi, sqrt, radians
from copy import deepcopy
import traceback

#for dumps
from inspect import getmembers
from pprint import pprint

import dxf2gcode.bootstrap.runtime_state as g
from dxf2gcode.domain.project.tool_settings import effective_tool

from dxf2gcode.domain.geometry.linegeo import LineGeo
from dxf2gcode.domain.geometry.arcgeo import ArcGeo
from dxf2gcode.domain.geometry.point import Point
from dxf2gcode.domain.project.shape import Geos
from dxf2gcode.domain.project.shape import Shape
from dxf2gcode.domain.toolpath.pocketmill import PocketMill
from dxf2gcode.domain.toolpath.pocketmove import PocketMove
from dxf2gcode.domain.toolpath.shapeoffset import *
from dxf2gcode.domain.toolpath.leadmove import (ERROR, LEAD_OFF, LEAD_RADIUS,
                                   LEAD_STARTMOVE, LEAD_STRAIGHT,
                                   SPACE_NOMINAL, SPACE_TOOL_CENTER, WARNING,
                                   build_exit_geometries, build_lead_in,
                                   build_overcut,
                                   get_overcut_enabled,
                                   get_lead_in_mode, get_lead_out_mode,
                                   lead_move_enabled, machine_g40_approach,
                                   reverse_chain, resolve_radius)

from dxf2gcode.presentation.qt.qt_compat import QtCore

import logging
logger = logging.getLogger('core.stmove')


class StMove(object):
    """
    This Function generates the StartMove for each shape. It
    also performs the Plotting and Export of this moves. It is linked
    to the shape of its parent
    """
    # only need default arguments here because of the change of usage with super in QGraphicsLineItem
    def __init__(self, shape=None):
        if shape is None:
            return

        self.shape = shape

        self.updateShape()

    def __repr__(self):
        return "StMove(shape %d start %s angle %s end %s)" % \
            (self.shape.nr, str(self.start), str(self.angle), str(self.end))

    def tr(self, string_to_translate):
        """
        Translate a string using the QCoreApplication translation framework
        @param: string_to_translate: a unicode string
        @return: the translated unicode string if it was possible to translate
        """
        return str(QtCore.QCoreApplication.translate("StMove",
                                                     string_to_translate))

    def append(self, geo):
        # we don't want to additional scale / rotate the stmove geo
        # so no geo.make_abs_geo(self.shape.parentEntity)
        geo.make_abs_geo()
        self.geos.append(geo)

    def _last_pass_is_mirrored(self):
        """
        True if the last depth pass of an open contour is the mirrored one.

        The open contours are milled in alternating directions: the first pass
        is the original direction, the second one is mirrored, the third one
        is the original again and so on. The cutter compensation is switched
        with every pass.

        @return: True if the last pass is the mirrored one
        """
        if self.shape.closed:
            return False
        try:
            number_of_passes = len(self.shape.get_pass_depths())
        except Exception:
            return False
        return number_of_passes % 2 == 0

    def set_break_chain(self, chain):
        """
        The chain of the last pass with the break (tab) hops.

        The tabs are not cut: the export hops over them. The preview of the
        exit geometry has to show the same, so the preview is built from this
        chain (the tabs are the gaps in the preview).

        @param chain: the chain with the break hops or None if the tabs can
                not be determined
        """
        self.break_chain = chain
        self.rebuild_exit_preview()

    def rebuild_exit_preview(self):
        """
        Recalculate the preview of the exit geometry.
        """
        chain = self.break_chain if self.break_chain else self.exit_chain
        if not chain:
            self.exit_geos = Geos([])
            return
        self._build_exit_preview(list(chain), self.lead_space)

    def _build_exit_preview(self, chain, space):
        """
        The preview of the lead out and the overcut: the geometry which is
        written at the end of the last pass.

        It is only used for the preview in the canvas - the export calculates
        the same geometry again with the geometry of the pass which is
        exported (see Shape.write_lead_out_and_overcut).

        Known limitations of the preview:
        * The drag knife has no preview: its overcut is inserted into the
          contour before the tip offset is applied, so the tip path of the
          overcut can not be derived from the toolpath here.

        @param chain: the chain of the toolpath of the last pass
        @param space: SPACE_NOMINAL (the machine compensates) or
                      SPACE_TOOL_CENTER (dxf2gcode compensates)
        """
        self.exit_geos = Geos([])
        layer = effective_tool(self.shape)
        lead_out_mode = get_lead_out_mode(self.shape)
        overcut_enabled = get_overcut_enabled(
            self.shape, g.config.vars.Lead_In_Out['overcut_enabled'])
        self.exit_error = ""
        if not lead_move_enabled():
            return
        if lead_out_mode == LEAD_OFF and not overcut_enabled:
            return
        chain = list(chain)
        if not chain:
            return
        side = self.lead_side
        if self._last_pass_is_mirrored():
            # The last pass is the mirrored one: the exit geometry is mirrored
            # as well. The free side (away from the material) is a physical
            # property, so relative to the reversed travel direction the lead
            # out has to curve to the other side. This holds for the machine
            # and for the internal cutter compensation.
            chain = reverse_chain(chain)
            side = -side
        exit_geos, status, message = build_exit_geometries(
            chain, side, space, layer.getToolRadius(), lead_out_mode,
            getattr(layer, 'lead_radius', 0.0), overcut_enabled,
            getattr(layer, 'overcut_length', 0.0), closed=self.shape.closed,
            lead_length=getattr(layer, 'lead_length', 0.0))
        if status == ERROR:
            # An invalid geometry is reported by the export, the preview
            # stays empty and the error is shown in the canvas.
            self.exit_error = message
            logging.warning(self.tr("Shape %i: %s") % (self.shape.nr,
                                                        message))
            return
        self.exit_geos = Geos(exit_geos)

    def _build_lead_in(self, start, angle, side, space,
                       use_lead_length=False):
        """
        Build the lead in of the given plane and append it to the start move.

        The lead in is only built if it is enabled (the mode of the layer is
        not 'off'). The radius is the common radius at the workpiece, it is
        converted into the radius of the given plane. The length is the
        common length of the straight part.

        @param start: the point where the lead in ends (the contour start of
                      the given plane)
        @param angle: the travel direction at the start point (rad)
        @param side: +1 = the lead in curves to the left of the travel
        @param space: SPACE_NOMINAL (the machine compensates the nominal lead
                      in) or SPACE_TOOL_CENTER (the lead in is already the
                      offset tool center path)
        @param use_lead_length: True = the configured lead length is the
                      straight part of the lead in (software compensation);
                      False keeps the historical tool center radius (G40)
        @return: True if the lead in could be built (or is not needed)
        """
        layer = effective_tool(self.shape)
        lead_in_mode = get_lead_in_mode(self.shape)
        if lead_in_mode not in (LEAD_STRAIGHT, LEAD_RADIUS, LEAD_STARTMOVE):
            return True
        if not lead_move_enabled():
            # The lathe is not supported by the lead in (the X axis is the
            # diameter there).
            return True

        lead_radius = getattr(layer, 'lead_radius', 0.0)
        lead_length = getattr(layer, 'lead_length', 0.0)
        tool_rad = layer.getToolRadius()
        geos, status, message = build_lead_in(start, angle, side,
                                              lead_radius, tool_rad,
                                              space, lead_in_mode,
                                              length=lead_length,
                                              use_lead_length=use_lead_length)
        if status == ERROR:
            self.start_move_error = message
            return False
        if status == WARNING:
            logging.warning(self.tr("Shape %i: %s") % (self.shape.nr, message))
        if not geos:
            # The start move is only generated with the machine compensation.
            return True

        # The dive point of the lead in is reached first, then the lead in
        # itself is cut.
        self.append(RapidPos(geos[0].Ps))
        for geo in geos:
            self.append(geo)
        self.lead_in_geos = Geos(geos)
        # By default the whole lead in is the tool center path which is cut
        # with G40 (the machine compensation lead in overrides this with its
        # nominal part, see make_start_moves).
        self.lead_in_nominal_index = len(self.lead_in_geos)
        return True

    def updateShape(self):
        """
        Update start move after shape is changed.
        """
        self.start, self.angle = self.shape.get_start_end_points(True, True)
        self.end = self.start

        self.geos = Geos([])
        # Index where the pocket mill geometries start (set by
        # make_start_moves); everything before belongs to the G41/G42
        # compensation contour or the start moves. Used by the canvas to
        # render them with different line widths.
        self.pocket_geos_start = 0
        # The geometry of the lead in (see core/leadmove.py). It is part of
        # self.geos (so that the canvas shows it), but it is exported
        # separately: with the machine compensation it is written before the
        # plunge, with the internal compensation it is part of the toolpath.
        self.lead_in_geos = Geos([])
        # The index in lead_in_geos where the nominal part of the lead in
        # begins (the machine compensation circle / start move writes the G40
        # part before G41/G42 and the nominal part after it). 0 (or the length)
        # means: the whole lead in is the tool center path.
        self.lead_in_nominal_index = 0
        # The side the lead in and the lead out curve to: +1 = left of the
        # travel direction, -1 = right of it. It is the free side of the
        # contour.
        self.lead_side = 1
        # The plane of the lead in / lead out: the machine compensation works
        # in the nominal plane, the internal compensation in the tool center
        # plane.
        self.lead_space = SPACE_TOOL_CENTER
        # The preview of the lead out and the overcut (the geometry which is
        # written at the end of the last pass). It is only used for the
        # preview in the canvas.
        self.exit_geos = Geos([])
        # The chain of the toolpath of the last pass: it is the base of the
        # preview of the exit geometry.
        self.exit_chain = []
        # The chain with the break (tab) hops. It is set by the canvas, which
        # knows the break layers (they are part of the layer contents).
        self.break_chain = None
        # An error message of the exit geometry (the lead out / the overcut):
        # the shape is not exported if it is set.
        self.exit_error = ""
        # An error message of the lead in calculation: the shape is not
        # exported if it is set.
        self.start_move_error = ""
        logging.debug("Updating the Start Move / Offset Geometry")
        self.make_start_moves()

    def make_start_moves(self):
        """
        This function called to create the start move. It will
        be generated based on the given values for start and angle.
        """
        self.geos = Geos([])
        # Signed distance of the pocket fill's reference contour from the
        # original contour (0 = original contour, +radius = offset outward,
        # -radius = offset inward). The pocket fill keeps its edge clearance
        # relative to this reference contour. 0.0 keeps the previous behaviour.
        self.pocket_fill_offset = 0.0
        # Geometry the pocket fill is derived from when the additional offset
        # (finishing allowance) shifts the milled contour. None means: the fill
        # works on the original contour (previous behaviour).
        self.pocket_wall_reference = None

        if g.config.machine_type == 'drag_knife':
            self.make_swivelknife_move()
            # All swivel knife geometries belong to the compensated toolpath
            self.pocket_geos_start = len(self.geos)
            return

        # Get tool radius based on tool diameter.
        tool_rad = effective_tool(self.shape).getToolRadius()

        # Calculate the starting point with and without compensation.
        start = self.start
        angle = self.angle

        ### drill cutted from here

        if self.shape.Drill == True:
            if isinstance(self.shape.geos[0], ArcGeo):
                start = self.shape.geos[0].abs_geo.O

            self.append(RapidPos(start))

            Ps_ein = start.get_arc_point(0,  tool_rad)

            # generate the start rad. and append it.
            circle = ArcGeo(Ps=Ps_ein, Pe=Ps_ein, O=start,
                               r=tool_rad, direction=1)

            self.append(circle)


        elif (not g.config.vars.Cutter_Compensation["done_by_machine"] and
                (self.shape.cut_cor != 40 or self.shape.Pocket)):
            # Software cutter compensation: the compensated contour is baked
            # into the exported geometry.
            #
            # For pocket milling the boundary pass offset is selected below
            # according to the configured pocket_compensation_mode. Non-pocket
            # shapes always keep the plain G41/G42 direction mapping.

            logging.debug("We have custom offset by tool")

            toolwidth = effective_tool(self.shape).getToolRadius()

            # Additional offset (finishing allowance) of this individual shape:
            # it is added to the cutter radius so that a roughing pass can leave
            # material which a following finishing pass removes. 0.0 keeps the
            # previous behaviour. A positive value shifts the compensated
            # toolpath away from the outline on the compensated side (outward
            # for outside contours, inward for inside contours/pockets), i.e.
            # it always leaves more material. Only the software cutter
            # compensation can apply it geometrically.
            extra_offset = getattr(self.shape, 'milling_offset', 0.0)
            comp_offset = toolwidth + extra_offset
            if comp_offset <= 0.0:
                # The additional offset cancels the cutter compensation, so no
                # valid compensated toolpath exists for this shape. Keep the
                # previous safe handling: warn and export nothing (Write_GCode
                # drops shapes whose stmove contains no geometry).
                logging.error(
                    self.tr("Shape %i: the additional offset (%.3f mm) cancels "
                            "the cutter compensation (tool diameter %.3f mm) - "
                            "the shape will NOT be milled!")
                    % (self.shape.nr, extra_offset,
                       effective_tool(self.shape).tool_diameter))
                self.pocket_geos_start = len(self.geos)
                return

            # Pockets honour the selected compensation exactly like contours.
            if self.shape.cut_cor == 41 and self.shape.cw is True:
                offtype = "out"
            elif self.shape.cut_cor == 41 and self.shape.cw is False:
                offtype = "in"
            elif self.shape.cut_cor == 42 and self.shape.cw is False:
                offtype = "out"
            elif self.shape.cut_cor == 42 and self.shape.cw is True:
                offtype = "in"
            else:
                offtype = "out"
            logger.debug("Shape.cw %s; shape.cut_cor %i; Offset in direction: %s" %(self.shape.cw, self.shape.cut_cor,offtype))

            if self.shape.Pocket and self.shape.cut_cor == 40:
                # G40 = no cutter compensation: the contour itself is the tool
                # center path (no radius offset). The pocket fill is appended
                # afterwards by the pocket block below.
                side = 1 if bool(self.shape.cw) else -1
                self.lead_side = side
                if not self._build_lead_in(start, angle, side,
                                           SPACE_TOOL_CENTER):
                    self.pocket_geos_start = len(self.geos)
                    return
                if not len(self.lead_in_geos):
                    self.append(RapidPos(start))
                self.geos += Geos(deepcopy(geo)
                                  for geo in self.shape.geos.abs_iter())
                # The preview of the lead out and the overcut.
                self.lead_space = SPACE_TOOL_CENTER
                self.exit_chain = list(self.shape.geos)
                self._build_exit_preview(self.exit_chain, SPACE_TOOL_CENTER)
            else:
                offshape = offShapeClass(parent = self.shape, offset = comp_offset, offtype = offtype)

                if len(offshape.rawoff) == 0:
                    # P1: No offset geometry was produced. Distinguish the
                    # expected border case (the selected cutter diameter removed
                    # the whole contour) from genuine computation failures, so
                    # the user gets a meaningful hint. With an empty stmove,
                    # Write_GCode skips this shape.
                    status = getattr(offshape, "offset_status", None)
                    tool_dia = effective_tool(self.shape).tool_diameter
                    if status == "vanished":
                        # Reliable border case: nothing left to mill.
                        if self.shape.Pocket:
                            logging.warning(
                                self.tr("Shape %i: the cutter diameter (%.3f mm) removes "
                                        "the whole boundary - only the pocket will be "
                                        "milled!") % (self.shape.nr, tool_dia))
                        else:
                            logging.warning(
                                self.tr("Shape %i cannot be milled: the selected cutter "
                                        "diameter (%.3f mm) leaves no valid toolpath for "
                                        "this contour.") % (self.shape.nr, tool_dia))
                    elif status in ("walk_overflow", "no_intersection",
                                    "exception"):
                        # A real computation problem, not an expected border case.
                        logging.error(
                            self.tr("Cutter compensation failed for shape %i (%s) - the "
                                    "shape will NOT be milled!")
                            % (self.shape.nr, status))
                    else:
                        # Unknown cause - keep the previous safe handling.
                        if self.shape.Pocket:
                            logging.warning(
                                self.tr("Cutter compensation failed for shape %i - only "
                                        "the pocket will be milled, the boundary pass is "
                                        "skipped!") % self.shape.nr)
                        else:
                            logging.error(
                                self.tr("Cutter compensation failed for shape %i - the "
                                        "shape will NOT be milled!") % self.shape.nr)

                if len(offshape.rawoff) > 0:
                    # The rapid positioning must target the start of the FIRST
                    # milling loop: after a loop split the sequence is rotated,
                    # so loops[0][0] is not necessarily rawoff[0]. Positioning
                    # at rawoff[0] instead would leave an unmarked gap which
                    # the post processor would cut as a straight line.
                    if offshape.loops:
                        start, angle = offshape.loops[0][0].get_start_end_points(True, True)
                    else:
                        start, angle = offshape.rawoff[0].get_start_end_points(True, True)

                    # The lead in of the internal compensation is calculated in
                    # the tool center plane and appended in front of the
                    # compensated contour. It is calculated here (and not
                    # added to the contour before the offset), so that the
                    # offset computation is not influenced by it.
                    # The side the lead in curves to: it is the side the tool
                    # center path is offset to (the free side).
                    side = 1 if ((offtype == "out") ==
                                 bool(self.shape.cw)) else -1
                    self.lead_side = side
                    if not self._build_lead_in(start, angle, side,
                                               SPACE_TOOL_CENTER,
                                               use_lead_length=True):
                        self.pocket_geos_start = len(self.geos)
                        return
                    if not len(self.lead_in_geos):
                        self.append(RapidPos(start))

                    # P2: Mill each loop as its own path; the loops are connected
                    # with rapid moves (retract / move / plunge) like the pocket
                    # milling paths.
                    prev_end = None
                    for loop in offshape.loops:
                        if not loop:
                            continue
                        if prev_end is not None:
                            self.append(PocketMove(prev_end, loop[0].Ps))
                        self.geos += loop
                        prev_end = loop[-1].Pe

                    # The preview of the lead out and the overcut (the
                    # internal compensation works in the tool center plane).
                    # It has to be built after the loops were appended: the
                    # chain of the toolpath is needed for it.
                    self.lead_space = SPACE_TOOL_CENTER
                    self.exit_chain = list(
                        self.geos[1 + len(self.lead_in_geos):])
                    self._build_exit_preview(self.exit_chain,
                                             SPACE_TOOL_CENTER)

                    if (self.shape.Pocket and
                            self.shape.cut_cor in (41, 42)):
                        # The pocket fill keeps its edge
                        # clearance relative to THIS compensated offset
                        # contour, so record how far it sits from the original
                        # contour (offtype "out" -> offset outward, +radius).
                        # Only the cutter radius is recorded here; the
                        # additional offset (finishing allowance) is applied to
                        # the fill stand-off in pocketmill so that it works the
                        # same way for every compensation direction.
                        self.pocket_fill_offset = (
                            -toolwidth if offtype == "in" else toolwidth)

                    if self.shape.Pocket and extra_offset:
                        # The additional offset (finishing allowance) shifts the
                        # contour the tool really mills, so the pocket grows (or
                        # shrinks) with it. Derive the pocket fill from that
                        # shifted contour ("wall" = compensated contour inset by
                        # the tool radius = original contour shifted by the extra
                        # offset to the compensated side) so the fill follows the
                        # additional offset.
                        wall_outside = ((offtype == "out") ==
                                        (extra_offset > 0.0))
                        wall = offShapeClass(
                            parent=self.shape, offset=abs(extra_offset),
                            offtype=("out" if wall_outside else "in"))
                        if wall.loops:
                            reference = Geos()
                            for loop in wall.loops:
                                reference += loop
                            self.pocket_wall_reference = reference

        elif self.shape.cut_cor == 40:
            # No cutter compensation: the shape contour itself is the tool
            # center path. (Pockets with G40 are handled by the software
            # compensation branch above so they are exported correctly.)
            # The lead in is calculated in the tool center plane, the free
            # side of the contour is the left side of a CW contour.
            side = 1 if bool(self.shape.cw) else -1
            self.lead_side = side
            if not self._build_lead_in(start, angle, side, SPACE_TOOL_CENTER):
                self.pocket_geos_start = len(self.geos)
                return
            if not len(self.lead_in_geos):
                self.append(RapidPos(start))

            # The preview of the lead out and the overcut. Without a cutter
            # compensation the contour itself is the tool center path.
            self.lead_space = SPACE_TOOL_CENTER
            self.exit_chain = list(self.shape.geos)
            self._build_exit_preview(self.exit_chain, SPACE_TOOL_CENTER)

        # Cutting Compensation Left / Right
        elif self.shape.cut_cor == 41 or self.shape.cut_cor == 42:
            side = 1 if self.shape.cut_cor == 41 else -1
            self.lead_side = side
            lead_in_mode = get_lead_in_mode(self.shape)
            if lead_in_mode in (LEAD_RADIUS, LEAD_STARTMOVE):
                # The circle and the start move are programmed in the nominal
                # plane: G41/G42 is activated after the plunge (see
                # shape.Write_GCode) and the machine then builds the tool
                # radius offset of the nominal lead in. The machine is
                # positioned directly at the compensated start of the nominal
                # lead in line; no separate G40 approach line is inserted.
                if not self._build_lead_in(start, angle, side,
                                           SPACE_NOMINAL):
                    self.pocket_geos_start = len(self.geos)
                    return
                # For lathe or other modes where lead move is disabled,
                # _build_lead_in returns True but does not populate lead_in_geos.
                if not self.lead_in_geos:
                    self.append(RapidPos(start))
                    self.pocket_geos_start = len(self.geos)
                    return
                nominal = Geos(list(self.lead_in_geos))
                tool_radius = effective_tool(self.shape).getToolRadius()
                # Calculate compensated start position of the first nominal segment
                first = nominal[0]
                line_length = first.Ps.distance(first.Pe)
                if line_length > eps:
                    direction = Point((first.Pe.x - first.Ps.x) / line_length,
                                      (first.Pe.y - first.Ps.y) / line_length)
                    # Offset direction: left for G41 (side>0), right for G42 (side<0)
                    if side > 0:
                        offset_dir = Point(-direction.y, direction.x)
                    else:
                        offset_dir = Point(direction.y, -direction.x)
                    compensated_start = first.Ps + offset_dir * tool_radius
                else:
                    compensated_start = first.Ps
                # All lead-in geometries are nominal (compensated by machine)
                self.lead_in_nominal_index = 0
                self.geos = Geos([RapidPos(compensated_start)] +
                                 list(self.lead_in_geos))
            else:
                # The straight lead in is programmed in the tool center
                # plane: the contour start offset to the compensation side by
                # the tool radius. It is cut with G40 (without cutter
                # compensation), so the tool is already at the correct
                # (offset) position when the machine compensation G41/G42 is
                # activated at the end of the lead in (see shape.Write_GCode).
                # The nominal contour itself is still compensated by the
                # machine.
                tool_radius = effective_tool(self.shape).getToolRadius()
                normal = Point(x=-sin(angle) * side, y=cos(angle) * side)
                offset_start = start + normal * tool_radius
                if not self._build_lead_in(offset_start, angle, side,
                                           SPACE_TOOL_CENTER):
                    self.pocket_geos_start = len(self.geos)
                    return
                if not len(self.lead_in_geos):
                    self.append(RapidPos(offset_start))

            # The coordinate space of the lead out preview does not depend on
            # the lead in mode: with the machine compensation G41/G42 the
            # contour and the lead out are programmed nominal (the machine
            # offsets them), so the lead out is also previewed in the nominal
            # plane - even if the lead in itself was programmed in the tool
            # center plane (LEAD_STRAIGHT).
            self.lead_space = SPACE_NOMINAL
            self.exit_chain = list(self.shape.geos)
            self._build_exit_preview(self.exit_chain, SPACE_NOMINAL)

        # Remember where the pocket mill geometries start. Everything before
        # belongs to the G41/G42 compensation contour (or the start moves).
        # If the shape is no pocket this equals the total geo count.
        self.pocket_geos_start = len(self.geos)

        # Pocket Milling - draw toolpath
        if self.shape.Pocket == True:
            # PocketMill expects a current position (stmove.geos[-1].Pe).
            # With a failed/vanished cutter compensation nothing was
            # appended so far - anchor the pocket at the shape start point
            # instead of crashing with an IndexError.
            if len(self.geos) == 0:
                self.append(RapidPos(self.start))
            
            pocket = PocketMill(self)
            try:
                pocket.createLines()
            except Exception:
                # Safety net: an unexpected error in the pocket calculation
                # must not crash the application nor leave a half-built
                # toolpath behind. Drop everything the pocket appended after
                # the boundary pass so no broken path is exported.
                del self.geos[self.pocket_geos_start:]
                logging.error(
                    self.tr("Pocket milling failed for shape %i - the pocket is "
                            "skipped. This is a bug, please report it with the "
                            "offending DXF file.\n%s")
                    % (self.shape.nr, traceback.format_exc()))
            
    def make_swivelknife_move(self):
        """
        Set these variables for your tool and material
        @param offset: knife tip distance from tool centerline. The radius of the
        tool is used for this.
        """
        offset = effective_tool(self.shape).getToolRadius()
        drag_angle = self.shape.drag_angle

        # The direction the knife points to when the cut starts. The default
        # (0 degree = positive X axis) is the behaviour of the program before
        # the start orientation became configurable.
        start_angle = radians(g.config.vars.Drag_Knife_Options[
            'drag_start_angle'])
        startnorm = offset * Point(cos(start_angle), sin(start_angle))
        prvend, prvnorm = Point(), Point()
        first = True

        # The overcut continues the cut along the existing contour beyond the
        # closing point. It is added to the contour BEFORE the contour is
        # shifted by the tip offset, so the tip path follows the contour over
        # the closing point as well.
        contour_geos = list(self.shape.geos.abs_iter())
        overcut_geos = []
        if (get_overcut_enabled(self.shape,
                                  g.config.vars.Lead_In_Out['overcut_enabled']) and
                lead_move_enabled()):
            overcut_length = getattr(effective_tool(self.shape), 'overcut_length',
                                     0.0)
            if overcut_length > 0.0 and self.shape.closed:
                # The overcut is only possible for closed contours: an open
                # contour is silently ignored (it is not an error).
                geos, status, message = build_overcut(contour_geos,
                                                       overcut_length)
                if status == ERROR:
                    self.start_move_error = message
                else:
                    overcut_geos = geos
        if overcut_geos:
            contour_geos = contour_geos + list(overcut_geos)

        for geo in contour_geos:
            if isinstance(geo, LineGeo):
                geo_b = deepcopy(geo)
                if first:
                    first = False
                    prvend = geo_b.Ps + startnorm
                    prvnorm = startnorm
                norm = offset * (geo_b.Pe - geo_b.Ps).unit_vector()
                geo_b.Ps += norm
                geo_b.Pe += norm
                if not prvnorm == norm:
                    direction = prvnorm.to3D().cross_product(norm.to3D()).z
                    swivel = ArcGeo(Ps=prvend, Pe=geo_b.Ps, r=offset, direction=direction)
                    swivel.drag = drag_angle < abs(swivel.ext)
                    logger.debug(swivel)
                    self.append(swivel)
                logger.debug(geo_b)
                self.append(geo_b)

                prvend = geo_b.Pe
                prvnorm = norm
            elif isinstance(geo, ArcGeo):
                geo_b = deepcopy(geo)
                if first:
                    first = False
                    prvend = geo_b.Ps + startnorm
                    prvnorm = startnorm
                if geo_b.ext > 0.0:
                    norma = offset*Point(cos(geo_b.s_ang+pi/2), sin(geo_b.s_ang+pi/2))
                    norme = Point(cos(geo_b.e_ang+pi/2), sin(geo_b.e_ang+pi/2))
                else:
                    norma = offset*Point(cos(geo_b.s_ang-pi/2), sin(geo_b.s_ang-pi/2))
                    norme = Point(cos(geo_b.e_ang-pi/2), sin(geo_b.e_ang-pi/2))
                geo_b.Ps += norma
                if norme.x > 0:
                    geo_b.Pe = Point(geo_b.Pe.x+offset/(sqrt(1+(norme.y/norme.x)**2)),
                                     geo_b.Pe.y+(offset*norme.y/norme.x)/(sqrt(1+(norme.y/norme.x)**2)))
                elif norme.x == 0:
                    geo_b.Pe = Point(geo_b.Pe.x,
                                     geo_b.Pe.y)
                else:
                    geo_b.Pe = Point(geo_b.Pe.x-offset/(sqrt(1+(norme.y/norme.x)**2)),
                                     geo_b.Pe.y-(offset*norme.y/norme.x)/(sqrt(1+(norme.y/norme.x)**2)))
                if prvnorm != norma:
                    direction = prvnorm.to3D().cross_product(norma.to3D()).z
                    swivel = ArcGeo(Ps=prvend, Pe=geo_b.Ps, r=offset, direction=direction)
                    swivel.drag = drag_angle < abs(swivel.ext)
                    logger.debug(swivel)
                    self.append(swivel)
                prvend = geo_b.Pe
                prvnorm = offset*norme
                if -pi < geo_b.ext < pi:
                    swivel = ArcGeo(Ps=geo_b.Ps, Pe=geo_b.Pe, r=sqrt(geo_b.r ** 2 + offset ** 2), direction=geo_b.ext)
                    logger.debug(swivel)
                    self.append(swivel)

                else:
                    geo_b = ArcGeo(Ps=geo_b.Ps, Pe=geo_b.Pe, r=sqrt(geo_b.r**2+offset**2), direction=-geo_b.ext)
                    geo_b.ext = -geo_b.ext
                    logger.debug(geo_b)
                    self.append(geo_b)
            # TODO support different geos, or disable them in the GUI
            # else:
            #     self.append(copy(geo))
        if not prvnorm == startnorm:
            direction = prvnorm.to3D().cross_product(startnorm.to3D()).z
            swivel = ArcGeo(Ps=prvend, Pe=prvend - prvnorm + startnorm, r=offset, direction=direction)
            swivel.drag = drag_angle < abs(swivel.ext)
            logger.debug(swivel)
            self.append(swivel)

        self.geos.insert(0, RapidPos(self.geos.abs_el(0).Ps))
        self.geos[0].make_abs_geo()


    def make_path(self, drawHorLine, drawVerLine):
        for geo in self.geos.abs_iter():
            drawVerLine(self.shape, geo.get_start_end_points(True))
            geo.make_path(self.shape, drawHorLine)
        if len(self.geos):
            drawVerLine(self.shape, geo.get_start_end_points(False))


class RapidPos(Point):
    def __init__(self, point):
        Point.__init__(self, point.x, point.y)
        self.abs_geo = None

    def get_start_end_points(self, start_point, angles=None):
        if angles is None:
            return self
        elif angles:
            return self, 0
        else:
            return self, Point(0, -1) if start_point else Point(0, -1)

    def make_abs_geo(self, parent=None):
        """
        Generates the absolute geometry based on itself and the parent. This
        is done for rotating and scaling purposes
        """
        self.abs_geo = RapidPos(self.rot_sca_abs(parent=parent))

    def make_path(self, caller, drawHorLine):
        pass
