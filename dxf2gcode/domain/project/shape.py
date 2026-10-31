# -*- coding: utf-8 -*-

############################################################################
#
#   Copyright (C) 2008-2015
#    Christian KohlÃ¶ffel
#    Vinzenz Schulz
#    Jean-Paul Schouwstra
#
#   Copyright (C) 20019-2020
#    San Zamoyski (PocketMill parts)
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

from math import radians, pi
from copy import deepcopy
import logging

import dxf2gcode.bootstrap.runtime_state as g
from dxf2gcode.domain.geometry.point import Point
from dxf2gcode.domain.geometry.linegeo import LineGeo
from dxf2gcode.domain.geometry.arcgeo import ArcGeo
from dxf2gcode.domain.geometry.holegeo import HoleGeo
from dxf2gcode.domain.geometry.breakgeo import BreakGeo
from dxf2gcode.domain.toolpath.pocketmove import PocketMove
from dxf2gcode.domain.toolpath.leadmove import (ERROR, LEAD_DEFAULT, LEAD_OFF,
                                    LEAD_RADIUS, LEAD_STARTMOVE, LEAD_STRAIGHT,
                                    OVERCUT_DEFAULT, SPACE_NOMINAL,
                                    SPACE_TOOL_CENTER,
                                    build_exit_geometries,
                                    get_lead_in_mode, get_lead_out_mode,
                                    get_overcut_enabled, lead_move_enabled,
                                    resolve_overcut)
from dxf2gcode.domain.toolpath.depths import calculate_depth_passes



import dxf2gcode.domain.constants as c
from dxf2gcode.presentation.qt.qt_compat import QtCore
from dxf2gcode.presentation.qt.qt_compat.QtWidgets import QMessageBox

logger = logging.getLogger("Core.Shape")


class Shape(object):

    """
    The Shape Class includes all plotting, GUI functionality and export functions
    related to the Shapes.
    """
    # only need default arguments here because of the change of usage with
    # super in QGraphicsItem

    def __init__(self, nr=-1, closed=True, parentEntity=None, geos=[]):
        if nr == -1:
            return

        self.type = "Shape"
        self.nr = nr
        self.closed = closed
        self.cut_cor = 40
        self.Pocket = False
        self.Drill = False
        self.parentEntity = parentEntity
        self.parentLayer = None
        self.tool_override = None
        self.geos = Geos(geos)

        self.cw = True

        self.stmove = None

        self.send_to_TSP = g.config.vars.Route_Optimisation['default_TSP']

        self.selected = False
        self.disabled = False
        self.allowedToChange = True
        # Optional presentation callbacks are plain callables. The domain
        # model does not import or depend on Qt.
        self.selectionChangedCallback = None
        self.enableDisableCallback = None

        # preset defaults
        self.axis3_start_mill_depth = g.config.vars.Depth_Coordinates[
            'axis3_start_mill_depth']
        self.axis3_slice_depth = g.config.vars.Depth_Coordinates[
            'axis3_slice_depth']
        self.axis3_mill_depth = g.config.vars.Depth_Coordinates[
            'axis3_mill_depth']
        self.f_g1_plane = g.config.vars.Feed_Rates['f_g1_plane']
        self.f_g1_depth = g.config.vars.Feed_Rates['f_g1_depth']
        # Parameters for drag knife
        self.drag_angle = radians(
            g.config.vars.Drag_Knife_Options['drag_angle'])

        # Break tab processing: -1 = last pass (default), 0 = never,
        # 1..n = process the tabs from this pass number on.
        self.break_pass = -1

        # Additional offset (finishing allowance) added to the tool radius of
        # the software cutter compensation. 0.0 keeps the previous behaviour.
        # The initial value is taken from the layer/tool the shape is attached
        # to (see LayerContent.overrideDefaults() and the shape window).
        self.milling_offset = 0.0

        # The overcut is a setting of the shape: OVERCUT_DEFAULT follows the
        # default of the parent layer / of the configuration file, OVERCUT_OFF
        # switches it off and OVERCUT_ON activates it. It is only used by
        # closed contours (an open contour ignores it silently). A mixed
        # selection (open and closed contours in the same layer) can therefore
        # switch the overcut on for the closed contours only.
        self.overcut_enabled = OVERCUT_DEFAULT
        self.overcut_enabled_overridden = False

        # The methods of the lead in and of the lead out are settings of the
        # shape too (like the milling depth): LEAD_DEFAULT follows the default
        # of the parent layer / of the configuration file, otherwise the shape
        # has its own method. So every contour can have its own lead in and
        # lead out.
        self.lead_in_mode = LEAD_DEFAULT
        self.lead_out_mode = LEAD_DEFAULT
        self.lead_in_mode_overridden = False
        self.lead_out_mode_overridden = False

    def _get_lead_mode(self, attribute):
        """
        The method of the lead in / lead out which is really used for this
        shape: the own value wins, LEAD_DEFAULT follows the parent layer
        (which resolves the standard of the configuration file).
        @param attribute: 'lead_in_mode' or 'lead_out_mode'
        @return: the method
        """
        mode = getattr(self, attribute, LEAD_DEFAULT)
        if mode is not None and mode != LEAD_DEFAULT:
            return mode
        layer = getattr(self, 'parentLayer', None)
        getter = getattr(layer, 'get_' + attribute, None)
        if getter is not None:
            return getter()
        return LEAD_OFF

    def get_lead_in_mode(self):
        """
        The method of the lead in which is really used for this shape.
        @return: the method
        """
        return self._get_lead_mode('lead_in_mode')

    def get_lead_out_mode(self):
        """
        The method of the lead out which is really used for this shape.
        @return: the method
        """
        return self._get_lead_mode('lead_out_mode')

    def get_overcut_enabled(self):
        """
        Whether the overcut is active for this shape.

        The own value wins; OVERCUT_DEFAULT follows the parent layer (which
        resolves the standard of the configuration file).
        @return: True if the overcut is active
        """
        if getattr(self, 'overcut_enabled', OVERCUT_DEFAULT) != \
                OVERCUT_DEFAULT:
            return resolve_overcut(self.overcut_enabled, False)
        layer = getattr(self, 'parentLayer', None)
        getter = getattr(layer, 'get_overcut_enabled', None)
        if getter is not None:
            return getter()
        return resolve_overcut(OVERCUT_DEFAULT, False)

    def __repr__(self):
        """
        Standard method to print the object
        @return: A string
        """

        #logger.debug(self.closed)
        return "Shape (nr=%i, closed=%s, geos=%s)" % \
                (self.nr, self.closed, self.geos)

    def tr(self, string_to_translate):
        """
        Translate a string using the QCoreApplication translation framework
        @param: string_to_translate: a unicode string
        @return: the translated unicode string if it was possible to translate
        """
        return str(QtCore.QCoreApplication.translate("Shape",
                                                           string_to_translate))

    def setSelected(self, flag=False):
        self.selected = flag

    def setSelectionChangedCallback(self, callback):
        self.selectionChangedCallback = callback

    def setEnableDisableCallback(self, callback):
        self.enableDisableCallback = callback

    def isSelected(self):
        return self.selected

    def setDisable(self, flag=False):
        self.disabled = flag

    def isDisabled(self):
        return self.disabled

    def isDrill(self):
        return self.Drill

    def setToolPathOptimized(self, flag=False):
        self.send_to_TSP = flag

    def isToolPathOptimized(self):
        return self.send_to_TSP

    def isDirectionOfGeosCCW(self, geos):
        # By calculating the area of the shape
        start = geos.abs_el(0).get_start_end_points(True)
        summe = 0.0
        for geo in geos.abs_iter():
            if isinstance(geo, LineGeo):
                end = geo.get_start_end_points(False)
                summe += (start.x + end.x) * (end.y - start.y)
                start = end
            elif isinstance(geo, ArcGeo):
                segments = 10
                for i in range(1, segments + 1):
                    end = geo.get_point_from_start(i, segments)
                    summe += (end.x + start.x) * (end.y - start.y)
                    start = end
        if not self.closed:
            # if shape is not closed... simply treat it as closed
            end = geos.abs_el(0).get_start_end_points(True)
            summe += (end.x + start.x) * (end.y - start.y)

        if summe == 0:  # inconclusive
            logger.debug(
                self.tr("Shoelace method cannot (directly) be applied to this shape"))
            # lets take it clock wise with relation to the workpiece zero

            start = geos.abs_el(0).get_start_end_points(True)
            # get the farthest end point with relation to the start
            end = start
            distance2 = 0
            for geo in geos.abs_iter():
                pos_end = geo.get_start_end_points(False)
                pos_distance2 = (start - pos_end).length_squared()
                if pos_distance2 > distance2:
                    end = pos_end
                    distance2 = pos_distance2
            direction = start.to3D().cross_product(end.to3D()).z
            # start and end are aligned wrt to wp zero
            if -1e-5 < direction < 1e-5:
                direction = start.length_squared() - end.length_squared()
            summe = direction
        return summe > 0.0

    def AnalyseAndOptimize(self):
        self.setNearestStPoint(Point())
        logger.debug(
            self.tr("Analysing the shape for CW direction Nr: %s" % self.nr))

        if self.isDirectionOfGeosCCW(self.geos):
            self.reverse()
            logger.debug(self.tr("Had to reverse the shape to be CW"))
        self.cw = True

    def setNearestStPoint(self, stPoint):
        if self.closed:
            logger.debug(self.tr("Clicked Point: %s" % stPoint))
            start = self.get_start_end_points(True)
            logger.debug(self.tr("Old Start Point: %s" % start))

            min_geo_nr, _ = min(enumerate(self.geos.abs_iter()),
                                key=lambda geo:
                                geo[1].get_start_end_points(True).distance(stPoint))

            # Overwrite the geometries in changed order.
            self.geos = Geos(self.geos[min_geo_nr:] + self.geos[:min_geo_nr])

            start = self.get_start_end_points(True)
            logger.debug(self.tr("New Start Point: %s" % start))
        elif len (self.geos) > 0:
            # if shape is not closed, we can just select between start and end points
            dist1 = self.geos.abs_el(0).get_start_end_points(True).distance(stPoint)
            dist2 = self.geos.abs_el(-1).get_start_end_points(False).distance(stPoint)
            if dist2 < dist1:
                self.reverse()

        # Update start move after reordering the shape
        if self.stmove is not None:
            self.stmove.updateShape()

    def setSharpestStPoint(self):
        """
        Loops over the geometries of a closed shape and searches the highest
        angle between the end geometry to the start geometry. The one with the 
        highest angle inbetween will be the new start point.        
        """           
            
        # Do only if more then 2 geometies of a closed shape
        if len(self.geos) < 2 and self.closed:
            return

        sharpest_ang=0.0
        max_index=0
        for i in range(len(self.geos)):
             end_point, end_ang = self.geos[i-1].get_start_end_points(0,1) 
             st_point,  st_ang  = self.geos[i].get_start_end_points(1,1)
             
             ang_diff=(st_ang-end_ang-pi)
             
             if ang_diff < -pi: 
                ang_diff += 2*pi
             if ang_diff > pi:
                ang_diff -=2*pi
                      
             logger.debug("st_point: %s; end_ang: %0.2f; st_ang: %0.2f; ang_diff: %0.2f" %(st_point, st_ang, end_ang, ang_diff))

             if sharpest_ang<abs(ang_diff):
                 sharpest_ang=abs(ang_diff)
                 sharpest_geo_nr=i             
             
        logger.debug("sharpest_ang: %0.2f " %(sharpest_ang))     
             
        # Overwrite the geometries in changed order.
        self.geos = Geos(self.geos[sharpest_geo_nr:] + self.geos[:sharpest_geo_nr])

        start = self.get_start_end_points(True)
        logger.debug(self.tr("New Start Point: %s" %start))


        # Update start move after reordering the shape
        if self.stmove is not None:
            self.stmove.updateShape()



    def reverse(self, geos=None):
        if not geos:
            geos = self.geos
            # switch direction if working with own geometry
            self.cw = not self.cw
        geos.reverse()
        for geo in geos:
            geo.reverse()

    def switch_cut_cor(self):
        """
        Switches the cutter direction between 41 and 42.

        G41 = Tool radius compensation left.
        G42 = Tool radius compensation right
        """
        if self.cut_cor == 41:
            self.cut_cor = 42
        elif self.cut_cor == 42:
            self.cut_cor = 41

    def append(self, geo):
        geo.make_abs_geo(self.parentEntity)
        self.geos.append(geo)

    def get_start_end_points_physical(self, start_point=None, angles=None, PPocket=False):
        """
        With multiple slices end point could be start point.
        e.g. useful for the optimal rout etc
        """
        
        if self.cw ==True:
            direction = -1;
        else:
            direction = 1;
            
        ### drill cut here
        
        #TODO: end point will change to zig-zag's end
        
        if start_point or self.closed:
            return self.get_start_end_points(start_point, angles)
        else:
            max_slice = max(self.axis3_slice_depth,
                            self.axis3_mill_depth -
                            self.axis3_start_mill_depth)
            if max_slice == 0:
                end_should_be_start = True
            else:
                end_should_be_start = (
                    self.axis3_start_mill_depth - self.axis3_mill_depth) // max_slice % 2 == 0
            if not end_should_be_start:
                return self.get_start_end_points(start_point, angles)
            else:
                start_stuff = self.get_start_end_points(True, angles)
                if angles is False:
                    end_stuff = start_stuff[0], -start_stuff[1]
                else:
                    end_stuff = start_stuff
                if start_point is None:
                    return start_stuff, end_stuff
                else:
                    return end_stuff

    def get_start_end_points(self, start_point=None, angles=None, PPocket=False):

        if self.cw ==True:
            direction = -1;
        else:
            direction = 1;
                  
        
        if start_point is None:
            return (self.geos.abs_el(0).get_start_end_points(True, angles),
                    self.geos.abs_el(-1).get_start_end_points(False, angles))
        elif start_point:
            return self.geos.abs_el(0).get_start_end_points(True, angles)
        else:
            return self.geos.abs_el(-1).get_start_end_points(False, angles)

    def make_path(self, drawHorLine, drawVerLine):

        for geo in self.geos.abs_iter():
            drawVerLine(self, geo.get_start_end_points(True))

            geo.make_path(self, drawHorLine)

        if not self.closed:
            drawVerLine(self, geo.get_start_end_points(False))

        self.calc_bounding_box()

    def calc_bounding_box(self):
        """
        Calculated the BoundingBox of the geometry and saves it into self.BB
        """
        self.BB = self.geos.abs_el(0).BB
        for geo in self.geos.abs_iter():
            self.BB = self.BB.joinBB(geo.BB)

    def make_shape_ccw(self):
        """
        This method is called after the shape has been generated before it gets
        plotted to change all shape direction to a CW shape.
        """

        if not(self.closed):
            return

        # Optimization for closed shapes
        # Start value for the first sum

        if self.isDirectionOfGeosCCW(self.geos):
            self.reverse()
            logger.debug(self.tr("Had to reverse the shape to be CW"))
        self.cw = True

    def isHit(self, xy, tol):
        if self.BB.Ps.x - tol <= xy.x <= self.BB.Pe.x + tol\
                and self.BB.Ps.y - tol <= xy.y <= self.BB.Pe.y + tol:
            for geo in self.geos.abs_iter():
                if geo.isHit(self, xy, tol):
                    return True
        return False





    def get_pass_depths(self, single_pass=False):
        """
        Returns the Z depths of all milling passes as they are written by
        Write_GCode(): the first pass at the initial mill depth followed by
        one pass per additional slice. The arithmetic mirrors the while loop
        in Write_GCode() exactly (same order of operations) so that the
        number and depth of the passes is always identical to the export.
        @param single_pass: True when the export is limited to a single pass
        (DXF output type or a drill without repeated drill moves).
        """
        return calculate_depth_passes(
            self.axis3_start_mill_depth,
            self.axis3_slice_depth,
            self.axis3_mill_depth,
            single_pass=single_pass)




    def join_colinear_lines(self):
        """
        This function is called to search for colinear connected lines an joins
        them if there are any

        The first and the last geometry of a closed polyline are not joined
        (they are connected at the closing point of the contour): the joined
        geometry would start at the start point of the last geometry, so the
        start point of the polyline would move to the end of the contour. The
        start point of a shape is the position of the lead in (and of the lead
        out, the contour is closed), so it must stay where the user set it.
        """
        # Do only if more then 2 geometies
        if len(self.geos) < 2:
            return

        new_geos = []
        for i in range(len(self.geos)):
            if len(new_geos) == 0:
                new_geos.append(self.geos[i])
                continue

            geo1 = new_geos[-1]
            geo2 = self.geos[i]

            if isinstance(geo1, LineGeo) and isinstance(geo2, LineGeo):
                # Remove first geometry and add result of joined geometries. Required
                # Cause the join will give back the last 2 geometries.
                new_geos.pop()
                new_geos += geo1.join_colinear_line(geo2)
            elif isinstance(geo1, ArcGeo) or isinstance(geo2, ArcGeo):
                new_geos.append(geo2)

            # If start end End Point are the same remove geometry
            if new_geos[-1].Ps == new_geos[-1].Pe:
                # Note that this can make new_geos absolutely empty!
                new_geos.pop()

        # For closed polylines the first and the last item may be colinear
        # too (they are connected at the closing point of the contour). They
        # are NOT joined here: the joined geometry would start at the start
        # point of the last geometry, so the start point of the closed
        # polyline would move to the end of the contour. The start point of a
        # shape is the position of the lead in (and of the lead out, the
        # contour is closed), so it must stay where the user set it.
        #
        # This is not an issue for the offset algorithm: the colinear vertex
        # is neither a convex nor a reflex point, it is simply skipped
        # (see make_segment_types).
        #
        # The case occurs with the "split line segments" option, where the
        # contour is cut in the middle of a line: the first and the last
        # geometry of the contour are then the two halves of that line and
        # therefore colinear.

        self.geos = new_geos


class Geos(list):

    def __init__(self, *args):
        list.__init__(self, *args)


    def __repr__(self):
        res = "Geos ("
        sep = "\n"
        for i in range(len(self)):
            res += sep
            res += "[%i] %s" % (i, repr(self[i]))
            sep = ",\n"
        res += ")"
        return res


    def abs_iter(self):
        for geo in list.__iter__(self):
            yield geo.abs_geo if geo.abs_geo else geo

    def rel_iter(self):
        for geo in list.__iter__(self):
            yield geo

    def abs_el(self, element):
        return self[element].abs_geo if self[element].abs_geo else self[element]
