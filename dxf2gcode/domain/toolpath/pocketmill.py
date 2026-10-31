# -*- coding: utf-8 -*-

############################################################################
#
#   Copyright (C) 2008-2015
#    Christian Kohlöffel
#    Vinzenz Schulz
#    Jean-Paul Schouwstra
#   
#   Copyright (C) 2019-2020 
#    San Zamoyski
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

from math import sin, cos, pi, sqrt, ceil, asin, floor
from copy import deepcopy
from bisect import bisect_left, bisect_right, insort

import dxf2gcode.bootstrap.runtime_state as g
from dxf2gcode.domain.project.tool_settings import effective_tool

from dxf2gcode.domain.geometry.linegeo import LineGeo
from dxf2gcode.domain.geometry.arcgeo import ArcGeo
from dxf2gcode.domain.geometry.point import Point
from dxf2gcode.domain.geometry.boundingbox import BoundingBox
from dxf2gcode.domain.project.shape import Geos
from dxf2gcode.domain.project.shape import Shape
from dxf2gcode.domain.toolpath.shapeoffset import *
from dxf2gcode.domain.toolpath.pocketmove import PocketMove

from dxf2gcode.presentation.qt.qt_compat import QtCore

import logging
logger = logging.getLogger('core.pocketmill')

# Historical pocket stand-off was "cutter radius / 0.7", i.e. an edge clearance
# of radius * (1 / 0.7 - 1) = 21.4286 % of the tool diameter. Used as a fallback
# when the configuration (or the new option) is unavailable so that old
# configurations keep the previous behaviour.
HISTORIC_POCKET_EDGE_CLEARANCE_PERCENT = 100.0 * 3 / 14

import time

class InterPoint(object):
    def __init__(self, x=0, y=0, i=0, mill = False):
        self.x = x
        self.y = y
        self.i = i
        self.mill = mill
        self.p = Point(x, y)
        
    def __str__ (self):
        return 'X ->%6.3f  Y ->%6.3f (%s) is %s' % (self.x, self.y, self.i, self.mill)
    
    def setMill(self, mill=False):
        self.mill = mill
        ### end of not-inside
        
class BBArray(object):
    def __init__(self, bbStartPoint, bbEndPoint, diff):
        #This class creates array filled with points (self.create())
        # they will be used to decide where to mill lines
        self.array = []
        self.any = False
        
        #Y-index for fast O(1) lookups during zig-zag milling
        self.points_by_y = {}

        # Row spans (first/last index of every grid row inside self.array),
        # built together with the Y-index. They let removeLine() touch only
        # the affected row instead of scanning the whole grid.
        self.row_span = {}
        
        #Start point - top, right
        
        if bbStartPoint.x > bbEndPoint.x:
            self.xStart = bbEndPoint.x
            self.xEnd   = bbStartPoint.x
        else: 
            self.xStart = bbStartPoint.x
            self.xEnd   = bbEndPoint.x

        if bbStartPoint.y > bbEndPoint.y:
            self.yStart = bbStartPoint.y
            self.yEnd   = bbEndPoint.y
        else: 
            self.yStart = bbEndPoint.y
            self.yEnd   = bbStartPoint.y
            
        #TODO: calculate diff size based on BBArray height 
        #TODO:  and minimal maximum diff (like on circle milling)
        self.diff = diff
        self.overUpRight = Point(self.xStart + 1, self.xStart + 1)
        self.overDownLeft = Point(self.xEnd - 1, self.xEnd - 1)
        self.overDistance = self.overUpRight.distance(self.overDownLeft)
        
        self.divY = 1
        self.divX = 4
            
        # All row Y values of the full grid (unmodified after create),
        # used to find geometric neighbour rows like the original code
        self.all_ys = []
            
    def create(self):
        #Fills array with InterPoints
        arrayIndex = 0 
        yi = self.yStart - self.diff / self.divY
            
        while yi > self.yEnd:
            xi = self.xStart + self.diff/self.divX
            while xi < self.xEnd:
                self.append(InterPoint(xi, yi, arrayIndex, True))
                xi += self.diff/self.divX
                arrayIndex += 1
            yi -= self.diff / self.divY
        
        # Full grid rows, sorted ascending; needed by findNextLine to
        # connect only to the geometric neighbour row (one step away)
        self.all_ys = sorted(set(pt.y for pt in self.array))
            
    def checkIfAny(self):
        return bool(self.points_by_y)

        
    def append(self, newPoint):
        #Adds point to array
        self.array.append(newPoint)
    
    def print(self):
        #This will stop work if array will be not in order
        #This function tries to dump to stdout whole array
        # in somehow readable way.
        if not self.array:
            # Nothing to dump (e.g. the tool is too large for the grid);
            # never index into an empty array.
            return
        yi = self.array[0].y
        print("%8.2f" % (yi) , end = "\t")
        
        for BBPoint in self.array:
                
            if BBPoint.y != yi:
                yi = BBPoint.y 
                print()
                print("%8.2f" % (yi) , end = "\t")
                
            if BBPoint.mill:
                print('T', end = ' ')
            else:
                print(' ', end = ' ')
                    
        print()
        
    def _build_y_index(self):
        """Pre-build a dict mapping y to sorted list of x-values for fast lookups."""
        self.points_by_y = {}
        self.row_span = {}
        for i, pt in enumerate(self.array):
            y_key = pt.y
            span = self.row_span.get(y_key)
            if span is None:
                self.row_span[y_key] = [i, i]
            else:
                span[1] = i
            if not pt.mill:
                continue
            if y_key not in self.points_by_y:
                self.points_by_y[y_key] = []
            insort(self.points_by_y[y_key], pt.x)
    
    def removeLine(self, line):
        """Remove milled points from index and array, keeping them in sync."""
        if line.Ps.x > line.Pe.x:
            line = LineGeo(line.Pe, line.Ps)
        
        yi = line.Ps.y
        left_x = min(line.Ps.x, line.Pe.x)
        right_x = max(line.Ps.x, line.Pe.x)
        
        # Remove from Y-index using sorted list slicing with bisect bounds
        if yi in self.points_by_y:
            xs = self.points_by_y[yi]
            li = bisect_left(xs, left_x)
            ri = bisect_left(xs, right_x + 0.0001)  # small epsilon for float comparison
            del self.points_by_y[yi][li:ri]
            if not self.points_by_y[yi]:
                del self.points_by_y[yi]
                
        # Mark the corresponding points as non-millable. Only the affected
        # grid row has to be touched (rows are contiguous in self.array), so
        # this stays O(row width) instead of scanning the whole grid.
        span = self.row_span.get(yi)
        if span is not None:
            array = self.array
            limit = right_x + 0.0001
            for i in range(span[0], span[1] + 1):
                pt = array[i]
                if pt.mill and left_x <= pt.x <= limit:
                    pt.setMill(False)
    
    def findHorizontalWithPoint(self, point):
        # Search the Y-index for the longest CONTIGUOUS millable line at
        # point.y that contains point.x. Index points sit on a grid with
        # spacing diff/divX; a removed (milled or out-of-shape) point
        # creates a gap of at least 2*step, so neighbours within 1.5*step
        # belong to the same segment. Returning only the segment prevents
        # milling across gaps between separate pocket areas.
        pts_x = self.points_by_y.get(point.y, [])
        if not pts_x:
            return LineGeo(point, point)
        
        idx = bisect_left(pts_x, point.x)
        if idx >= len(pts_x):
            idx = len(pts_x) - 1
        
        step = self.diff / self.divX
        tol = step * 1.5
        
        left = idx
        while left > 0 and (pts_x[left] - pts_x[left - 1]) <= tol:
            left -= 1
        
        right = idx
        while right < len(pts_x) - 1 and (pts_x[right + 1] - pts_x[right]) <= tol:
            right += 1
        
        min_true = pts_x[left]
        max_true = pts_x[right]
        
        dist_left = abs(point.x - min_true)
        dist_right = abs(point.x - max_true)
        
        if dist_left <= dist_right:
            return LineGeo(Point(min_true, point.y), Point(max_true, point.y))
        else:
            return LineGeo(Point(max_true, point.y), Point(min_true, point.y))
    
    def findNextLine(self, line, preferTop):
        # Tries to find line over or under given line to be milled.
        # It prefers top or bottom, and returns new preferences ;)
        # It returns preferTop = True if it finds Bottom.
        currentY = line.Ps.y
        currentX = line.Pe.x
        
        if line.Ps.x < line.Pe.x:
            xRangeStart = line.Ps.x
            xRangeEnd   = line.Pe.x
        else:
            xRangeStart = line.Pe.x
            xRangeEnd   = line.Ps.x
        
        # Geometric neighbour rows on the full grid (exactly one row step
        # away), like the original linear implementation. Connecting only
        # to adjacent rows prevents long vertical jump moves across
        # already-milled or empty rows (which would cut through material).
        # all_ys is sorted ascending; rows above currentY have larger y.
        pos_top = bisect_right(self.all_ys, currentY + 1e-9)
        topY = self.all_ys[pos_top] if pos_top < len(self.all_ys) else None
        
        pos_bot = bisect_left(self.all_ys, currentY - 1e-9) - 1
        bottomY = self.all_ys[pos_bot] if pos_bot >= 0 else None
        
        if topY is None and bottomY is None:
            return None, preferTop
        
        # Remaining millable points of the neighbour rows within the
        # current line's X range (points_by_y only holds unmilled points,
        # equivalent to the original mill==True filter)
        xListTop = [x_val for x_val in self.points_by_y.get(topY, []) 
                     if xRangeStart <= x_val <= xRangeEnd] if topY is not None else []
        xListBottom = [x_val for x_val in self.points_by_y.get(bottomY, []) 
                        if xRangeStart <= x_val <= xRangeEnd] if bottomY is not None else []
                        
        if (preferTop == True or len(xListBottom) == 0) and len(xListTop) > 0:
            if abs(currentX - min(xListTop)) > abs(currentX - max(xListTop)):
                return self.findHorizontalWithPoint(Point(max(xListTop), topY)), False
            else:
                return self.findHorizontalWithPoint(Point(min(xListTop), topY)), False
        elif (preferTop == False or len(xListTop) == 0) and len(xListBottom) > 0:
            if abs(currentX - min(xListBottom)) > abs(currentX - max(xListBottom)):
                return self.findHorizontalWithPoint(Point(max(xListBottom), bottomY)), True
            else:
                return self.findHorizontalWithPoint(Point(min(xListBottom), bottomY)), True
        else:
            return None, preferTop
                
        
    def findClosestEnd(self, point):
        # Looks for most-bottom and most-top y's.
        # For those two looks for most-lefts and most-rights.
        # Then checks which one is closest, so milling will start 
        # from closest most-far line and most-close point.
        if not self.points_by_y:
            return None
        
        # Get existing Y values from index
        ys_in_range = list(self.points_by_y.keys())
        if not ys_in_range:
            return None
            
        topY = max(ys_in_range)
        bottomY = min(ys_in_range)
        
        # Get extreme X values at these Y positions
        top_xs = self.points_by_y[topY] if topY in self.points_by_y else []
        bottom_xs = self.points_by_y[bottomY] if bottomY in self.points_by_y else []
        
        topLeftX = top_xs[0] if top_xs else self.xEnd - 1
        topRightX = top_xs[-1] if top_xs else self.xStart + 1
        bottomLeftX = bottom_xs[0] if bottom_xs else self.xEnd - 1
        bottomRightX = bottom_xs[-1] if bottom_xs else self.xStart + 1
        
        points = [
            Point(topLeftX, topY),
            Point(topRightX, topY),
            Point(bottomLeftX, bottomY),
            Point(bottomRightX, bottomY)]
        
        distance = self.overDistance
        closestPoint = None
        
        for p in points:
            if point.distance(p) < distance:
                distance = point.distance(p)
                closestPoint = p
        
        if closestPoint is None:
            # Fallback: none of the four extreme grid ends is within
            # overDistance. This happens e.g. for a G40 pocket whose start
            # point (the first contour vertex, see PocketMill.createLines) is
            # farther away than overDistance. There ARE millable points
            # (checked above), so do not abort the zig-zag - start at the
            # nearest of the four extreme ends. They are real millable row
            # ends inside the pocket area, so this is geometrically safe.
            closestPoint = min(points, key=point.distance)
        
        return closestPoint        
    
class PocketMill(object):
    def __init__(self, stmove=None):
        #It gets stmove object and do whole magic with it:
        # creates paths for pocket milling
        self.stmove = stmove
        
        # Get tool radius based on tool diameter.
        self.tool_rad = effective_tool(self.stmove.shape).getToolRadius()
        
        self.bbarray = 0
        
        self.arrayYStart = 0
        self.arrayYEnd = 0
        self.arrayXStart = 0
        self.arrayXEnd = 0
        
        self.diff = 0
        
        self.dist = 0
        
        self.inters = []

    def tr(self, string_to_translate):
        """
        Translate a string using the QCoreApplication translation framework
        @param: string_to_translate: a unicode string
        @return: the translated unicode string if it was possible to translate
        """
        return str(QtCore.QCoreApplication.translate("PocketMill",
                                                     string_to_translate))

    def _reference_geos(self):
        """Geometry the pocket fill is derived from.

        Normally the shape contour. The additional offset (finishing allowance)
        shifts the contour the tool really mills, so the pocket grows (or
        shrinks) with it: ``StMove.pocket_wall_reference`` then holds that
        shifted contour ("wall") and the fill is derived from it. Cached
        because the fill code queries it repeatedly.
        """
        reference = getattr(self, "_ref_geos", None)
        if reference is None:
            reference = getattr(self.stmove, "pocket_wall_reference", None)
            if not reference:
                reference = self.stmove.shape.geos
            self._ref_geos = reference
        return reference

    def _reference_bb(self):
        """Bounding box of the geometry the pocket fill is derived from."""
        reference = self._reference_geos()
        if reference is self.stmove.shape.geos:
            return self.stmove.shape.BB
        xs = []
        ys = []
        for geo in reference.abs_iter():
            xs += [geo.Ps.x, geo.Pe.x]
            ys += [geo.Ps.y, geo.Pe.y]
            if isinstance(geo, ArcGeo):
                xs += [geo.O.x - geo.r, geo.O.x + geo.r]
                ys += [geo.O.y - geo.r, geo.O.y + geo.r]
        return BoundingBox(Point(min(xs), min(ys)), Point(max(xs), max(ys)))

    def removeNearShape(self):
        #Looks for points in array that are too close to shape
        # to be milled.
        #
        # Broad-phase filter, geometry-outer: a grid point can only be closer
        # than self.dist to a geometry if it lies inside that geometry's
        # bounding box expanded by self.dist. The grid is grouped by row
        # (rows and their x values are already sorted, see BBArray.create),
        # so for every geometry only the rows and columns inside its expanded
        # box are visited. That avoids the previous O(points * geometries)
        # exact distance evaluations without changing the result.
        dist = self.dist
        rows = {}
        for point in self.bbarray.array:
            rows.setdefault(point.y, []).append(point)
        ys = sorted(rows.keys())
        row_xs = {}
        for y, points in rows.items():
            row_xs[y] = [p.x for p in points]

        for geo in self._reference_geos().abs_iter():
            if isinstance(geo, LineGeo):
                gx0 = geo.Ps.x
                gx1 = geo.Pe.x
                gy0 = geo.Ps.y
                gy1 = geo.Pe.y
                if gx0 > gx1:
                    gx0, gx1 = gx1, gx0
                if gy0 > gy1:
                    gy0, gy1 = gy1, gy0
                is_line = True
            elif isinstance(geo, ArcGeo):
                # conservative box of the full circle (always contains the arc)
                o = geo.O
                gx0 = o.x - geo.r
                gx1 = o.x + geo.r
                gy0 = o.y - geo.r
                gy1 = o.y + geo.r
                is_line = False
            else:
                continue

            x0 = gx0 - dist
            x1 = gx1 + dist
            y0 = gy0 - dist
            y1 = gy1 + dist

            for k in range(bisect_left(ys, y0), bisect_right(ys, y1)):
                y = ys[k]
                points = rows[y]
                xs = row_xs[y]
                start = bisect_left(xs, x0)
                end = bisect_right(xs, x1)
                for t in range(start, end):
                    point = points[t]
                    if not point.mill:
                        continue
                    if is_line:
                        if geo.distance_l_p(point.p) < dist:
                            point.setMill(False)
                    else:
                        if geo.distance_a_p(point.p) < dist:
                            point.setMill(False)
    def movePoint(self, point):
        #Moves point by particular value (addX and Y are
        # calculated before creating "point")
        #in fact point is an array [point, addX, addY]
        return [Point(point[0].x + point[1], point[0].y + point[2]), point[1], point[2]]
                        
    def removeOutOfShape(self):
        #Check all points in array if they are inside (self.inters) or
        # outside shape. If they are outside, it sets them 
        # to mill= False
        
        # Pre-index intersections by Y so that lookups are O(1) groups
        # instead of O(len(self.inters)) per BBPoint — critical for large bboxes
        inters_by_y = {}
        for pinter in self.inters:
            y_key = pinter.y
            if y_key not in inters_by_y:
                inters_by_y[y_key] = []
            inters_by_y[y_key].append(pinter)
        
        for BBPoint in self.bbarray.array:
            count = 0
            
            if BBPoint.mill == True:
                for pinter in inters_by_y.get(BBPoint.y, ()):
                    if pinter.x > BBPoint.x:
                        count += 1
            
            if count%2 == 0:
                BBPoint.setMill(False)
            
    def createInterList(self):
        yi = self.bbarray.yStart - self.diff/self.bbarray.divY
        #this while loop will prepare points that crosses the shape.
        # it will be used later to check if point lays inside shape.
        # imagine horizontal line from particular point up to the end
        # of BBox containing shape. if the line crosses shape even times
        # we are outside the shape.
        #
        # Every geometry contributes its crossings using a consistent
        # half-open rule (lower endpoint inclusive, upper endpoint
        # exclusive). This keeps the even-odd parity in removeOutOfShape()
        # correct at shared vertices/tangencies and never emits a crossing
        # outside the real extent of a segment (see the ticket #176 fix).
        while yi > self.bbarray.yEnd:
            for interGeo in self._reference_geos().abs_iter():
                if isinstance(interGeo, LineGeo):
                    x = self._line_horizontal_intersection(interGeo, yi)
                    if x is not None:
                        self.inters.append(Point(x, yi))
                elif isinstance(interGeo, ArcGeo):
                    for x in self._arc_horizontal_intersections(interGeo, yi):
                        self.inters.append(Point(x, yi))

            yi -= self.diff/self.bbarray.divY
            #print("End of finding intersections")

    @staticmethod
    def _pocket_edge_clearance_percent():
        """Pocket edge clearance as a percentage of the tool diameter.

        Returns the historical value (cutter radius / 0.7 stand-off) when the
        configuration or the option is missing, so old configurations keep
        working unchanged.
        """
        try:
            return float(g.config.vars.Pocketing.pocket_edge_clearance)
        except Exception:
            return HISTORIC_POCKET_EDGE_CLEARANCE_PERCENT

    @staticmethod
    def _line_horizontal_intersection(geo, yi):
        """X coordinate where the line segment ``geo`` crosses ``y = yi``.

        Uses a half-open Y rule (lower endpoint inclusive, upper endpoint
        exclusive) so shared vertices are counted exactly once and horizontal
        segments contribute no crossing. Returns ``None`` when the segment does
        not cross ``yi``.

        Unlike the previous implementation this checks the segment's real
        extent in X *and* Y and never relies on an exact float equality to
        detect vertical lines, so vertical, near-vertical, horizontal and
        slanted segments are all handled correctly.
        """
        y0 = geo.Ps.y
        y1 = geo.Pe.y
        if not ((y0 <= yi < y1) or (y1 <= yi < y0)):
            return None
        return geo.Ps.x + (yi - y0) * (geo.Pe.x - geo.Ps.x) / (y1 - y0)

    @staticmethod
    def _arc_horizontal_intersections(arc, yi):
        """X coordinates where the arc crosses the horizontal line ``y = yi``.

        The arc is split at its Y extrema into monotone runs and the same
        half-open Y rule as for line segments is applied to every run. This
        keeps the even-odd parity consistent at shared vertices and at
        tangencies (a run touching ``yi`` at its extreme adds no crossing) and
        avoids duplicate crossings. The arc orientation (``ext``) is respected.
        """
        O = arc.O
        r = arc.r
        ext = arc.ext
        if abs(ext) <= 1e-12:
            return []

        k = (yi - O.y) / r
        if k < -1.0 - 1e-8 or k > 1.0 + 1e-8:
            return []
        k = max(-1.0, min(1.0, k))

        # A complete circle is handled without endpoint logic (it is normally
        # caught by the circle special case in createLines()).
        if abs(ext) >= 2 * pi - 1e-8:
            if abs(k) >= 1.0 - 1e-12:
                return []
            d = sqrt(max(0.0, 1.0 - k * k))
            return [O.x - r * d, O.x + r * d]

        s_ang = arc.s_ang
        if ext > 0:
            lo, hi = 0.0, ext
        else:
            lo, hi = ext, 0.0

        # Parameters t in [lo, hi] where dy/dt = r*cos(s_ang + t) vanishes,
        # i.e. the Y extrema that split the arc into monotone runs.
        splits = []
        base = pi / 2 - s_ang
        m = floor((lo - base) / pi) - 1
        m_end = ceil((hi - base) / pi) + 1
        while m <= m_end:
            t = base + m * pi
            if lo + 1e-9 < t < hi - 1e-9:
                splits.append(t)
            m += 1

        ts = [lo] + sorted(splits) + [hi]
        result = []
        for i in range(len(ts) - 1):
            ta, tb = ts[i], ts[i + 1]
            if tb - ta <= 1e-12:
                continue
            ya = O.y + r * sin(s_ang + ta)
            yb = O.y + r * sin(s_ang + tb)
            if not ((ya <= yi < yb) or (yb <= yi < ya)):
                continue
            a_lo = s_ang + min(ta, tb)
            a_hi = s_ang + max(ta, tb)
            # sin(s_ang + t) == k has two base solutions; exactly one of them
            # lies inside this monotone run.
            base_a = asin(k)
            for cand in (base_a, pi - base_a,
                         base_a + 2 * pi, pi - base_a + 2 * pi,
                         base_a - 2 * pi, pi - base_a - 2 * pi):
                if a_lo - 1e-9 <= cand <= a_hi + 1e-9:
                    x = O.x + r * cos(cand)
                    if not result or abs(result[-1] - x) > 1e-9:
                        result.append(x)
                    break
        return result

    def createLines(self):
        #This function will decide what kind of shape do we deal with
        # then creates milling lines and move paths.
        circle = 0
        horizontalRectangle = 0

        geosNum = len(self._reference_geos())
        print("Number of geos: %s" % (geosNum))
        
        cutComp = self.stmove.shape.cut_cor
            
        if len(self.stmove.geos) == 0:
            # Nothing was appended before the pocket (the caller normally
            # anchors the pocket at the shape start point).
            realStart = self._reference_geos()[0].Ps
        else:
            lastGeo = self.stmove.geos[-1]
            # RapidPos marks the current position and has no Pe attribute
            realStart = lastGeo.Pe if hasattr(lastGeo, 'Pe') else lastGeo
        
        #set the proper direction for the tool path
        if self.stmove.shape.cw ==True:
            direction = -1;
        else:
            direction = 1;
        
        if geosNum == 2:
            if self._reference_geos()[0].r == self._reference_geos()[1].r and self._reference_geos()[0].Ps == self._reference_geos()[1].Pe and self._reference_geos()[0].Pe == self._reference_geos()[1].Ps:
                    circle = 1
                    
        if geosNum == 4:
            hLines = 0
            vLines = 0
            linesNum = 0

            for gLine in self._reference_geos():
                if isinstance(gLine, LineGeo) and gLine.Ps.x == gLine.Pe.x:
                    vLines += 1
                if isinstance(gLine, LineGeo) and gLine.Ps.y == gLine.Pe.y:
                    hLines += 1
                    
            if hLines == 2 and vLines == 2:
                horizontalRectangle = 1

        if self._reference_geos() is not self.stmove.shape.geos:
            # The additional offset shifted the milled contour, so the
            # pocket grows (or shrinks) with it. Use the general fill, which
            # honours the configured stand-off, instead of the special cases,
            # so the fill follows the shifted contour consistently.
            circle = 0
            horizontalRectangle = 0

        currentPoint = self.stmove.start
            
        if False:
            print("beans shape")
            #TODO: beans shape:  (____)
        elif False:
            #TODO: "Only lines and <180 angle.
            print("Only lines and <180 angle.")
        elif circle == 1:
            stepOverlay = 0.9
            
            #this is radius of whole shape
            if cutComp == 40: #no compensation
                millRad = self._reference_geos()[0].r - self.tool_rad
            elif cutComp == 41: #outside
                millRad = self._reference_geos()[0].r
            elif cutComp == 42: #comp inside
                millRad = self._reference_geos()[0].r - 2 * self.tool_rad

            rotNum = (millRad - 2 * self.tool_rad * stepOverlay)/(self.tool_rad * (1 + stepOverlay))
            rotNum = ceil(rotNum)

            # Guard against a geometrically impossible circular pocket and
            # against a division by zero (rotNum == 0). rotNum must NOT simply
            # be forced to 1 here - that could produce an invalid toolpath.
            # Instead skip the pocket cleanly; a possibly existing boundary
            # pass is left untouched.
            if millRad <= 0 or rotNum <= 0:
                logger.warning(
                    self.tr("Shape %i: a circular pocket cannot be milled with cutter "
                            "diameter %.3f mm (usable radius %.3f mm) - pocket skipped.")
                    % (self.stmove.shape.nr,
                       effective_tool(self.stmove.shape).tool_diameter, millRad))
                return

            stepOverlay = (millRad - rotNum * self.tool_rad)/(self.tool_rad * 2 * rotNum)
            currentRad = millRad - self.tool_rad * stepOverlay
            
            circleOff = self.tool_rad * (1 + stepOverlay)

            centerPoint = self._reference_geos()[0].O
            print("Shape radius: %s, circle rotNum: %s, stepOverlay: %s." % (self._reference_geos()[0].r, rotNum + 1, stepOverlay))

            currentPoint = realStart
            rLimit = self.tool_rad * (1 - stepOverlay)
            
            while currentRad > rLimit:
                
                print("CurrentRad: %s, limit %s." % (currentRad, rLimit))
                
                goToPoint = Point(centerPoint.x + currentRad, centerPoint.y)
                
                if centerPoint.y == currentPoint.y and centerPoint.x < currentPoint.x:
                    self.stmove.append(LineGeo(currentPoint, goToPoint))
                else:
                    self.stmove.append(PocketMove(currentPoint, goToPoint))
                    
                currentPoint = goToPoint
                
                self.stmove.append(ArcGeo(Ps = currentPoint, Pe = currentPoint, O = centerPoint, r = currentRad, direction = direction))
                
                currentRad -= circleOff
                
            self.stmove.append(PocketMove(currentPoint, realStart))
                        
        elif horizontalRectangle == 1:
            #rad varsus rad*2^(1/2) is 0,707106781
            stepOverlay = 0.7
            #hRectangleOff = 0.7 * self.tool_rad
            startTop = 0
            startLeft = 0
            
            #calculate center point
            xes = []
            yes = []

            for geo in self._reference_geos():
                xes.append(geo.Ps.x)
                yes.append(geo.Ps.y)
                
            centerPoint = Point(sum(xes)/4, sum(yes)/4)
            
            if realStart.x < centerPoint.x and realStart.y < centerPoint.y:
                #start is left-bottom corner
                print("start is left-bottom corner")
                startTop = 0
                startLeft = 1
                
            elif realStart.x > centerPoint.x and realStart.y < centerPoint.y:
                print("start is right-bottom corner")
                startTop = 0
                startLeft = 0
                
            elif realStart.x < centerPoint.x and realStart.y > centerPoint.y:
                print("start is left-top corner")
                startTop = 1
                startLeft = 1
                
            elif realStart.x > centerPoint.x and realStart.y > centerPoint.y:
                print("start is right-top corner")
                startTop = 1
                startLeft = 0
            
            #distance between center and farrest mill line
            xOff = abs(centerPoint.x - self._reference_geos()[0].Ps.x)
            yOff = abs(centerPoint.y - self._reference_geos()[0].Ps.y)

            # NOTE: this special case for simple 4-line rectangles uses the
            # cutter radius directly as the fill stand-off (edge clearance 0)
            # and does not yet honour the configurable "pocket edge clearance"
            # that the general fill below uses.
            if self.stmove.shape.cut_cor == 41:
                xOff += self.tool_rad
                yOff += self.tool_rad
            elif self.stmove.shape.cut_cor == 42:
                xOff -= self.tool_rad
                yOff -= self.tool_rad
            
            #Off = 2*stepOverlay*self.tool_rad + n*(1+stepOverlay)*self.tool_rad + tool_rad
            # n*(1+stepOverlay)*self.tool_rad = Off - 2*stepOverlay*self.tool_rad - tool_rad
            # n = (Off - 2*stepOverlay*self.tool_rad - tool_rad)/((1+stepOverlay)*self.tool_rad)
            numRotX = (xOff - 2*stepOverlay*self.tool_rad - self.tool_rad)/(self.tool_rad * (1 + stepOverlay))
            numRotY = (yOff - 2*stepOverlay*self.tool_rad - self.tool_rad)/(self.tool_rad * (1 + stepOverlay))
            
            numRot = ceil(min(numRotX, numRotY))

            # A negative rotation count means the (compensated) pocket is
            # smaller than the cutter; also avoid the division by
            # (numRot + 2) becoming zero. Skip the pocket cleanly.
            if numRot < 0 or xOff <= 0 or yOff <= 0:
                logger.warning(
                    self.tr("Shape %i: a rectangular pocket cannot be milled with "
                            "cutter diameter %.3f mm (tool too large for the pocket "
                            "area) - pocket skipped.")
                    % (self.stmove.shape.nr,
                       effective_tool(self.stmove.shape).tool_diameter))
                return
            
            #Off = 2*stepOverlay*self.tool_rad + n*(1+stepOverlay)*self.tool_rad + tool_rad
            # Off - tool_rad - n*self.tool_rad = 2*stepOverlay*self.tool_rad + n*stepOverlay*self.tool_rad
            # (Off - tool_rad - n*self.tool_rad)/(2*self.tool_rad + n*self.tool_rad) = stepOverlay
            stepOverlayX = (xOff - numRot * self.tool_rad - self.tool_rad)/((numRot + 2) * self.tool_rad)
            stepOverlayY = (yOff - numRot * self.tool_rad - self.tool_rad)/((numRot + 2) * self.tool_rad)
            
            if stepOverlayX > stepOverlay:
                stepOverlayX = stepOverlay
                
            if stepOverlayY > stepOverlay:
                stepOverlayY = stepOverlay
            
            print("Number of rotations: %s." % (numRot))
            
            #check first point and where it is
            # and build array of points calculated
            # from self.tool_rad and first point
            # for CW and CCW
            pointLeftBottom = Point(centerPoint.x - xOff + self.tool_rad * (1 + stepOverlayX),
                                centerPoint.y - yOff + self.tool_rad * (1 + stepOverlayY))
            
            pointLeftTop = Point(centerPoint.x - xOff + self.tool_rad * (1 + stepOverlayX),
                                centerPoint.y + yOff - self.tool_rad * (1 + stepOverlayY))
            
            pointRightTop = Point(centerPoint.x + xOff - self.tool_rad * (1 + stepOverlayX),
                                centerPoint.y + yOff - self.tool_rad * (1 + stepOverlayY))
            
            pointRightBottom = Point(centerPoint.x + xOff - self.tool_rad * (1 + stepOverlayX),
                                centerPoint.y - yOff + self.tool_rad * (1 + stepOverlayY))
            
            #also calculade addX and addY values, so next time 
            # corner-point will be in right place.
            stepX = (1 + stepOverlayX) * self.tool_rad
            stepY = (1 + stepOverlayY) * self.tool_rad 
            
            if startLeft == 1 and startTop == 0:
                pointList = [
                    [pointLeftBottom, Point(stepX, 0)],
                    [pointLeftTop, Point(stepX, -stepY)],
                    [pointRightTop, Point(-stepX, -stepY)],
                    [pointRightBottom, Point(-stepX, stepY)]
                    ]
                addAfter = Point(0, stepY)
                
            elif startLeft == 0 and startTop == 0:
                pointList = [
                    [pointRightBottom, Point(0, stepY)],
                    [pointLeftBottom, Point(stepX, stepY)],
                    [pointLeftTop, Point(stepX, -stepY)],
                    [pointRightTop, Point(-stepX, -stepY)]
                    ]
                addAfter = Point(-stepX, 0)
                
            elif startLeft == 1 and startTop == 1:
                pointList = [
                    [pointLeftTop, Point(0, -stepY)],
                    [pointRightTop, Point(-stepX, -stepY)],
                    [pointRightBottom, Point(-stepX, stepY)],
                    [pointLeftBottom, Point(stepX, stepY)]
                    ]
                addAfter = Point(stepX, 0)
                
            elif startLeft == 0 and startTop == 1:
                pointList = [
                    [pointRightTop, Point(-stepX, 0)],
                    [pointRightBottom, Point(-stepX, stepY)],
                    [pointLeftBottom, Point(stepX, stepY)],
                    [pointLeftTop, Point(stepX, -stepY)]
                    ]
                addAfter = Point(0, -stepY)
                
            #CW => -1, CCW => 1
            if direction == 1:
                #if CCW, change list direction
                tmp = pointList[1]
                pointList[1] = pointList[3]
                pointList[3] = tmp
                #correct addAfter
                tmp1 = pointList[0][1]
                pointList[0][1] = addAfter
                addAfter = tmp1
                
            #TODO: convert it to move based on horizontal and vertical lines only
            #TODO:  or check if it is needed.
            self.stmove.append(LineGeo(realStart, pointList[0][0]))
            
            i = 0
            
            #go throught all points until center
            while numRot >= i:
                print("Rot: %s/%s." % (i, numRot))
                self.stmove.append(LineGeo(pointList[0][0], pointList[1][0]))
                pointList[0][0] += pointList[0][1]
                self.stmove.append(LineGeo(pointList[1][0], pointList[2][0]))
                pointList[1][0] += pointList[1][1]
                self.stmove.append(LineGeo(pointList[2][0], pointList[3][0]))
                pointList[2][0] += pointList[2][1]
                self.stmove.append(LineGeo(pointList[3][0], pointList[0][0]))
                pointList[3][0] += pointList[3][1]
                
                currentPoint = pointList[0][0]
                i += 1
                pointList[0][0] += addAfter
                
            #go back to start point
            self.stmove.append(PocketMove(currentPoint, realStart))
            
            #done!
            
        else:
            #this is universal way to make pocket-milling
            # it (after making contour) will do zig-zag
            # inside shape. It is not extremely optimised
            # but should work for every kind of shape.
            
            #rad varsus rad*2^(1/2) is 0,707106781
            self.diff = self.tool_rad*2 * 0.7
            
            compType = self.stmove.shape.cut_cor
            
            #Compensation:
            # 42 - inside
            # 41 - outside
            # 40 - no compensation
            print("Compensations type: %s." % (compType))
            
            #print('BB: ' + self.stmove.shape.BB)
            print("self.stmove.BB: %s" % self.stmove.shape.BB)

            bb = self._reference_bb()
            self.bbarray = BBArray(bb.Ps, bb.Pe, self.diff)

            print("BBBounds: X%s to X%s, Y%s to Y%s" % (self.bbarray.xStart, self.bbarray.xEnd, self.bbarray.yStart, self.bbarray.yEnd))
            
            # The pocket fill keeps the configured edge clearance c relative to
            # the OFFSET contour selected by the compensation direction:
            #     clearance c = pocket_edge_clearance [% of tool diameter] * dia
            #     d           = cutter radius + c   (cutter CENTER to offset contour)
            # The cutter radius is therefore counted once and the percentage is
            # only the additional clearance (it never replaces the radius).
            #
            # The offset contour is `signed_offset` away from the original
            # contour (0 = no compensation, +radius = offset outward,
            # -radius = offset inward). Expressed as a stand-off from the
            # ORIGINAL contour this is |signed_offset - d|; that equals the
            # distance to the offset contour wherever the offset is a parallel
            # curve and stays robust where an offset contour would vanish.
            clearance = self._pocket_edge_clearance_percent() / 100.0 * (2 * self.tool_rad)
            d = self.tool_rad + clearance
            signed_offset = getattr(self.stmove, "pocket_fill_offset", 0.0) or 0.0
            self.dist = abs(signed_offset - d)

            ### fill array with TRUEs
            self.bbarray.create()
            ### end of filling array with TRUEs

            if not self.bbarray.array:
                # With this cutter diameter the step-over (self.diff) is
                # larger than the pocket bounding box, so no valid fill grid
                # exists. Handle it like the expected border case instead of
                # crashing on an empty grid and never emit a bogus toolpath.
                logger.warning(
                    self.tr("Shape %i: pocket cannot be milled with cutter diameter "
                            "%.3f mm (the tool is too large for the pocket area) - "
                            "pocket skipped.")
                    % (self.stmove.shape.nr,
                       effective_tool(self.stmove.shape).tool_diameter))
                return

            ### keep the cutter center clear of the contour so the cutting
            ### edge does not cut into (or past) the contour
            self.removeNearShape()
          
            #imagine parallel, horizontal lines (distance of self.diff)
            # this function will find all intersections of those lines
            # with shape.
            self.createInterList()
            
            self.removeOutOfShape()
            
            # Build Y-index for fast O(1) lookup in the zig-zag algorithm
            self.bbarray._build_y_index()
                                  
            ### ### ###
            ### Cool! We have now complete array of points to mill
            ### but we need to convert it into LINES now...
                    
            currentPoint = realStart
            milledAny = False
                                     
            while self.bbarray.checkIfAny():
                #Find start for new zig-zag and go there.
                closestPoint = self.bbarray.findClosestEnd(currentPoint)
                if closestPoint is None:
                    break
                closestLine = self.bbarray.findHorizontalWithPoint(closestPoint)
                goToPoint = closestLine.Ps
                
                self.stmove.append(PocketMove(currentPoint, goToPoint))
                currentPoint = goToPoint
                
                preferTop = True
                                                 
                while True:
                    #currentPoint should be one of bbarray.mill = true now
                    # so we are between Ps and Pe of next line at Y height
                    #Do first line from starting point 
                    line = self.bbarray.findHorizontalWithPoint(currentPoint)    #dir
                    
                    #If we are not at start point, go there
                    if currentPoint.x != line.Ps.x:
                        self.stmove.append(LineGeo(currentPoint, line.Ps))                        
                    
                    self.stmove.append(line)
                    milledAny = True
                    self.bbarray.removeLine(line)
                    currentPoint = line.Pe
                    
                    #Now we need to check if there is any near line we can go
                    line, preferTop = self.bbarray.findNextLine(line, preferTop)
                    
                    if line is None:
                        break
                    
                    #check if we can go straight up, or we need to do some stuff...
                    if not (line.Ps.x <= currentPoint.x <= line.Pe.x or line.Ps.x >= currentPoint.x >= line.Pe.x):
                        #we need to do some stuff: go back under next line
                        goToPoint = Point(line.Ps.x, currentPoint.y)
                        self.stmove.append(LineGeo(currentPoint, goToPoint))
                        currentPoint = goToPoint
                        
                    #Ok, go straight up, and end on nextLine (somewhere 
                    # between or on start/end point
                    goToPoint = Point(currentPoint.x, line.Ps.y)
                    self.stmove.append(LineGeo(currentPoint, goToPoint))
                    currentPoint = goToPoint

                #self.stmove.append(LineGeo(currentPoint, self.stmove.end))
            if milledAny:
                self.stmove.append(PocketMove(currentPoint, realStart))
            else:
                # No cutting line survived (e.g. the whole pocket area is
                # closer to the contour than the tool radius). Do not emit a
                # degenerate PocketMove(start, start) as a successful pocket.
                logger.warning(
                    self.tr("Shape %i: pocket cannot be milled with cutter diameter "
                            "%.3f mm - no reachable pocket area, pocket skipped.")
                    % (self.stmove.shape.nr,
                       effective_tool(self.stmove.shape).tool_diameter))
