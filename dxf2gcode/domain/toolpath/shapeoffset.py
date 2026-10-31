# -*- coding: utf-8 -*-

############################################################################
#
#   Copyright (C) 2008-2015
#    Christian Kohlöffel
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

from math import atan2, pi, sqrt, sin, cos
from copy import deepcopy
import logging

from dxf2gcode.domain.geometry.linegeo import LineGeo
from dxf2gcode.domain.geometry.arcgeo import ArcGeo
from dxf2gcode.domain.geometry.point import Point
from dxf2gcode.domain.project.shape import Geos
from dxf2gcode.domain.project.shape import Shape

import dxf2gcode.bootstrap.runtime_state as g

logger = logging.getLogger('core.shapeoffset')

eps = 1e-6
min_length=0.01



class offShapeClass(Shape):

    """
    This Class is used to generate The fofset aof a shape according to:
    "A pair-wise offset Algorithm for 2D point sequence curve"
    http://citeseerx.ist.psu.edu/viewdoc/summary?doi=10.1.1.101.8855
    """

    def __init__(self, parent=None, offset=1, offtype='in'):
        """
        Standard method to initialize the class
        @param closed: Gives information about the shape, when it is closed
        this value becomes 1. Closed means it is a Polygon, otherwise it is a
        Polyline
        @param length: The total length of the shape including all geometries
        @param geos: The list with all geometries included in the shape. May
        also contain arcs. These will be reflected by multiple lines in order
        to easy calclations.
        """

        super(offShapeClass, self).__init__(nr=parent.nr,
                                            closed=parent.closed,
                                            geos=[])

        #logger.debug("The shape is: %s" % (self.closed))

        self.offset = offset
        self.offtype = offtype
        self.segments = Geos()
        self.rawoff = []
        # P2: The raw offset curve split into separate loops (list of geo
        # lists). Each loop is milled as its own path; the caller connects
        # the loops with rapid moves (like the pocket milling paths).
        self.loops = []
        # P2: Intersection points of LIR removals which removed at least one
        # segment - pinch points where separate milling regions meet.
        self.split_cips = []

        # Offset computation status, so the caller can distinguish the
        # expected border case "the cutter diameter removed the whole
        # contour" from genuine computation failures:
        #   "pending"        - not finished yet
        #   "ok"             - valid offset geometry was produced
        #   "vanished"       - the interference handling removed the whole
        #                      remaining geometry (Begin = End; Remove all)
        #   "walk_overflow"  - the pairwise walk hit its safety limit
        #   "no_intersection"- a required intersection point was missing
        #   "exception"      - an exception occurred during the computation
        #   "unknown"        - empty result without a reliably known cause
        self.offset_status = "pending"

        self.geos_preprocessing(parent)

        self.make_segment_types()

        # Each convex vertex is resolved exactly once. The pairwise walk (or
        # the local miter fallback) must remove the vertex placeholder; if a
        # vertex can not be resolved safely the whole offset is REJECTED
        # instead of returning an invalid (gouging) toolpath.
        self.counter = 0
        n_segments = len(self.segments)
        resolved_guard = 0

        while True:
            cv_index = None
            for i, e in enumerate(self.segments):
                if isinstance(e, ConvexPoint):
                    cv_index = i
                    break
            if cv_index is None:
                break

            # Safety: every pass either removes segments (LIR / local miter)
            # or rejects the offset, so the loop is bounded.
            resolved_guard += 1
            if resolved_guard > 2 * n_segments + 4:
                self._reject_offset("walk_overflow")
                return

            # The pairwise walk has to start and end on a real edge. The
            # segments right before/after a convex vertex can be further
            # vertex placeholders (ConvexPoint/OffPoint without a Ps
            # attribute) when several arcs collapse. Skip all of them. For an
            # open contour the search must NOT wrap around the ends.
            forward_start = self._next_edge_index(cv_index + 1, 1)
            backward_start = self._next_edge_index(cv_index - 1, -1)
            if (forward_start is None or backward_start is None or
                    forward_start == backward_start):
                # A vertex at/near the open end (or a degenerate contour) has
                # no edge to be mitred against - not resolvable.
                self._reject_offset("vertex_not_resolvable")
                return

            try:
                result = self.PairWiseInterferenceDetection(
                    forward_start, backward_start)
            except Exception:
                self._reject_offset("exception")
                logger.exception("Not able to finish cutter compensation "
                                 "without error - Skipping it")
                return

            forward = backward = None
            if isinstance(result, tuple) and len(result) == 2:
                forward, backward = result

            if forward is None:
                # The cyclic pairwise walk did not resolve this vertex.
                if self.closed:
                    # For a closed contour the cyclic walk is the defined
                    # algorithm; keep its previous handling (counter overflow
                    # / no partial-partial found).
                    self._reject_offset("walk_overflow")
                    return
                # Open contour: the walk reached a free end. Resolve the
                # vertex locally: miter the raw offsets of the two
                # neighbouring edges and remove every placeholder in between.
                if not self._resolve_vertex_locally(cv_index, forward_start,
                                                    backward_start):
                    self._reject_offset("vertex_not_resolvable")
                    return
                continue

            if (backward == 0 and
                    forward == (len(self.segments) - 1) and
                    self.closed):
                # Begin = End; Remove all: forward and backward walk meet
                # on the same segment, i.e. the whole remaining raw offset
                # interferes and nothing is left to mill.
                self.offset_status = "vanished"
                self.segments = Geos()
                break

            # Make Raw offset curve of forward and backward segment
            fw_rawoff_seg = self.make_rawoff_seg(self.segments[forward])
            bw_rawoff_seg = self.make_rawoff_seg(self.segments[backward])

            # Intersect the two segements
            iPoint = fw_rawoff_seg.find_inter_point(bw_rawoff_seg, typ="TIP")


            if iPoint is None:
                logger.debug("forward: %s, backward: %s, iPoint: %s" % (
                    forward, backward, iPoint))
                logger.debug("fw_rawoff_seg: %s, bw_rawoff_seg: %s" % 
                             (fw_rawoff_seg, bw_rawoff_seg))

                logger.warning("No intersection found?!")
                self._reject_offset("no_intersection")
                return

            if isinstance(iPoint, list):
                logger.debug("forward: %s, backward: %s, iPoint: %s" % (
                    forward, backward, iPoint))
                logger.debug("fw_rawoff_seg: %s, bw_rawoff_seg: %s" % 
                             (fw_rawoff_seg, bw_rawoff_seg))
                logger.debug(iPoint[0])
                logger.debug(iPoint[1])
                logger.warning("Found more then one intersection points?! Using first one")
                iPoint = iPoint[0]


            # Remove the LIR from the PS Curce
            self.remove_LIR(forward, backward, iPoint)

        for seg in self.segments:
            self.rawoff += [self.make_rawoff_seg(seg)]

        # Snapshot of the raw offset before the interference removal. The
        # collapse guard after split_into_loops() uses it to detect a broken
        # GIR walk which would otherwise silently return a nearly empty
        # toolpath with the status "ok".
        raw_count = len(self.rawoff)
        raw_len = sum(geo.length for geo in self.rawoff)


        self.geos_postprocessing(eps*5)

        # GIR (Choi & Park 1999): the raw offset curve may still
        # self-intersect after the LIR removal (global interferences).
        # Every self-intersection seeds the unchanged pairwise walk; the
        # collected interference regions are trimmed at their crossings,
        # so the remaining loops stay CLOSED (the former heuristic
        # gouging cleanup is kept as a fallback method below).
        self.remove_global_interferences()

        # If parent shape is ccw, switch direction. This MUST happen
        # before the loops are built: reverse() flips the raw offset
        # sequence and every geometry - splitting afterwards keeps the
        # loop chains consistent with the final geometry direction.
        if parent.cw != self.cw:
            self.reverse()

        # P2b: Split the raw offset curve into separate loops at the
        # broken connections. Each loop is milled as its own path and the
        # caller connects the loops with rapid moves.
        self.split_into_loops()

        # Safety net: a GIR (or a broken walk) must never reduce a full
        # contour to a single element. That is a numerical/algorithmic
        # collapse, not a valid toolpath, and it must not be reported as
        # "ok" (otherwise the user gets a nearly empty toolpath without any
        # error). A real global interference removes a sub-region of the
        # offset, not the whole curve.
        if raw_count >= 3:
            loop_count = sum(len(loop) for loop in self.loops)
            loop_len = sum(geo.length for loop in self.loops
                           for geo in loop)
            if loop_count <= 1 or (raw_len > 0 and
                                   loop_len < 0.01 * raw_len):
                self.offset_status = "incomplete"
                logger.error(
                    "Cutter compensation: the offset collapsed to %i "
                    "element(s) (%i raw elements) - the shape will NOT be "
                    "milled", loop_count, raw_count)
                self.rawoff = Geos()
                self.loops = []
                return

        # Geometric self check: a raw offset arc of a collapsed vertex (which
        # would gouge) or any other dropout must never be returned as a valid
        # toolpath - reject the contour instead.
        #
        # It is applied to OPEN contours only. The cyclic GIR handling of
        # closed contours is deliberately left unchanged (out of scope here);
        # all closed contours keep their previous behaviour.
        if self.rawoff and not self.closed:
            ok, reason = self._validate_offset()
            if not ok:
                logger.warning("Cutter compensation: the calculated offset is "
                               "not a valid toolpath (%s) - the shape will "
                               "NOT be milled" % reason)
                self._reject_offset("invalid_geometry")
                return

        # Final classification: a non-empty raw offset is a valid result.
        # An empty result keeps whatever cause was recorded above; a truly
        # unknown empty result is never silently treated as "vanished".
        if self.rawoff:
            self.offset_status = "ok"
        elif self.offset_status == "pending":
            self.offset_status = "unknown"

    def _reject_offset(self, status):
        """
        Reject the offset: no valid toolpath could be calculated. Nothing is
        milled (the caller sees an empty rawoff) and a controlled status is
        kept for the caller and the log - an invalid toolpath is never
        returned as a valid result.
        @param status: the reason ("vertex_not_resolvable", "no_intersection",
                "exception", "walk_overflow", "invalid_geometry")
        """
        self.offset_status = status
        self.segments = Geos()
        self.rawoff = []
        self.loops = []

    def _next_edge_index(self, start, step):
        """
        The index of the first real edge (a segment with a Ps attribute)
        starting at `start` and searching in direction `step`. Vertex
        placeholders (ConvexPoint/OffPoint) are skipped.

        A closed contour wraps around once; an open contour does NOT wrap, so
        None is returned when an end is reached.
        @return: the index or None
        """
        n = len(self.segments)
        if n == 0:
            return None
        i = start
        for _ in range(n):
            if self.closed:
                i %= n
            elif i < 0 or i >= n:
                return None
            if hasattr(self.segments[i], 'Ps'):
                return i
            i += step
        return None

    def _resolve_vertex_locally(self, cv_index, forward, backward):
        """
        Local miter for a convex vertex whose cyclic pairwise walk did not
        resolve it (for an open contour the walk stops at a free end). The raw
        offsets of the two neighbouring edges are trimmed at their
        intersection and every placeholder between them is removed - the same
        operation remove_LIR() does, but without the cyclic walk.
        @return: True on success, False if the two offsets do not intersect
                (the offset can then not be calculated safely)
        """
        fw_rawoff = self.make_rawoff_seg(self.segments[forward])
        bw_rawoff = self.make_rawoff_seg(self.segments[backward])
        iPoint = fw_rawoff.find_inter_point(bw_rawoff, typ="TIP")
        if iPoint is None:
            return False
        if isinstance(iPoint, list):
            if not iPoint:
                return False
            vertex = self.segments[cv_index]
            vp = Point(vertex.x, vertex.y)
            iPoint = min(iPoint, key=lambda q: vp.distance(Point(q.x, q.y)))
        self.remove_LIR(forward, backward, iPoint)
        return True

    def _dist_point_geo(self, p, geo):
        """
        The shortest distance between a point and a geometry (line segment or
        arc). Exact for the geometry types used here.
        """
        if isinstance(geo, ArcGeo):
            if geo.PointAng_withinArc(p):
                return abs(p.distance(geo.O) - geo.r)
            return min(p.distance(geo.Ps), p.distance(geo.Pe))
        if isinstance(geo, LineGeo):
            return geo.distance_l_p(p)
        return min(p.distance(geo.Ps), p.distance(geo.Pe))

    def _min_distance_to_contour(self, p):
        best = 1e18
        for geo in self.geos:
            d = self._dist_point_geo(p, geo)
            if d < best:
                best = d
        return best

    def _nearest_source(self, p):
        """
        The source geometry nearest to `p` and the distance to it.
        @return: (distance, geo)
        """
        best_d, best_geo = 1e18, None
        for geo in self.geos:
            d = self._dist_point_geo(p, geo)
            if d < best_d:
                best_d, best_geo = d, geo
        return best_d, best_geo

    def _point_on_correct_side(self, p, geo, target):
        """
        Whether an offset point lies on the side of the source geometry that
        the offset direction (offtype) requires.

        The offset geometry is built with the source normal scaled by the
        offset sign (see make_rawoff_seg), so a valid offset point must lie on
        that side. The test is deliberately conservative: near the endpoints
        of a geometry (a round join / miter) and whenever the closest point is
        ambiguous it returns True (no rejection). Only a point which is
        CLEARLY on the opposite side of an interior part of a geometry is
        rejected, so legitimate joins and tangential touches cause no false
        alarm. The margin is half the tool radius.
        @return: True (keep) or False (definitely on the wrong side)
        """
        offset_used = -1.0 if self.offtype == "out" else 1.0
        margin = 0.5 * target
        if isinstance(geo, LineGeo):
            dd = geo.Pe - geo.Ps
            length2 = dd.dotProd(dd)
            if length2 <= 0.0:
                return True
            t = (p - geo.Ps).dotProd(dd)
            if t <= 0.05 * length2 or t >= 0.95 * length2:
                return True
            n = geo.Ps.get_normal_vector(geo.Pe)
            return (p - geo.Ps).dotProd(n) * offset_used > -margin
        if isinstance(geo, ArcGeo):
            if not geo.PointAng_withinArc(p):
                return True
            q = geo.O.get_arc_point(
                atan2(p.y - geo.O.y, p.x - geo.O.x), geo.r)
            if q.distance(geo.Ps) < 0.05 * target or \
                    q.distance(geo.Pe) < 0.05 * target:
                return True
            n = geo.O.unit_vector(q, r=1)
            if geo.ext < 0:
                n = n * -1.0
            return (p - q).dotProd(n) * offset_used > -margin
        return True

    def _sample_offset_point(self, geo, t):
        if isinstance(geo, ArcGeo):
            return geo.O.get_arc_point(geo.s_ang + geo.ext * t, geo.r)
        if isinstance(geo, LineGeo):
            return Point(geo.Ps.x + (geo.Pe.x - geo.Ps.x) * t,
                         geo.Ps.y + (geo.Pe.y - geo.Ps.y) * t)
        return geo.Ps

    def _validate_offset(self, segments_per_geo=8):
        """
        Geometric self check of the calculated offset (the ACTUAL toolpath,
        i.e. the loops, not the intermediate raw offset). Every point of every
        loop must keep the tool distance to the source contour: a miter or
        round join point lies on the offset curves, while the raw offset arc
        of a collapsed convex vertex (radius = offset around the source arc
        center with radius r < offset) is closer to the source and is NOT a
        valid toolpath.
        @return: (ok, reason)
        """
        if not self.rawoff and not self.loops:
            return True, ""
        target = abs(self.offset)
        # A gouge between the toolpath and the source contour is a region where
        # the distance drops below the tool radius; its extent scales with
        # sqrt(tool radius * deviation). With a tolerance of 1 % of the tool
        # radius such a region is at least ~0.28 * radius long, so a sampling
        # spacing of 0.1 * radius guarantees that a deviation above the
        # tolerance is hit by at least one sample (the previous fixed 9
        # samples per geometry missed a real ~0.93 mm long gouge on a
        # 10.9 mm long segment).
        tol = max(1e-4, target * 1e-2)
        min_spacing = 0.1 * target
        for loop in self.loops:
            # Continuity within the loop (the chains are cut at the gaps, but
            # a wrong join would produce a jump across the material).
            for k in range(len(loop) - 1):
                if loop[k].Pe.distance(loop[k + 1].Ps) > eps * 10:
                    return False, "the toolpath is not continuous"
            # Non-adjacent self intersections (a valid offset does not cross
            # itself).
            if self._find_crossings(loop):
                return False, "the toolpath intersects itself"
            # Tool distance to the source contour and the correct side (the
            # offset must not lie on the opposite side of the contour).
            for geo in loop:
                n = segments_per_geo
                length = getattr(geo, "length", 0.0) or 0.0
                if length > 0.0 and min_spacing > 0.0:
                    n = max(n, min(int(length / min_spacing) + 1, 500))
                for k in range(n + 1):
                    p = self._sample_offset_point(geo, k / float(n))
                    d, src_geo = self._nearest_source(p)
                    if abs(d - target) > tol:
                        return False, ("offset point is %.4f mm from the "
                                       "contour (expected %.4f mm)"
                                       % (d, target))
                    if not self._point_on_correct_side(p, src_geo, target):
                        return False, ("offset point lies on the wrong side "
                                       "of the contour")
        return True, ""

    def __repr__(self):
        """
        Standard method to print the object
        @return: A string
        """

        return "\nnr:          %i" % self.nr + \
               "\nclosed:      %s" % self.closed + \
               "\ngeos:        %s" % self.geos + \
               "\nofftype:     %s" % self.offtype + \
               "\noffset:      %s" % self.offset + \
               "\nsegments:    %s" % self.segments + \
               "\nrawoff       %s" % self.rawoff

    def reverse(self, geos=None):
        super().reverse(geos)
        # If working with own geometry, toggle rawoff direction too
        if not geos:
            self.rawoff.reverse()
            for geo in self.rawoff:
                geo.reverse()

    def geos_preprocessing(self, parent):
        """
        Do all the preprocessing required in order to have working offset
         algorithm.
        @param parent: The parent shape including the geometries to
        be offsetted.
        """
        
        logging.debug("Doing Preprocessing")

        self.geos = Geos([])
        if self.closed:
            last_Pe = parent.geos[-1].Pe.rot_sca_abs(parent=parent.parentEntity)
        else:
            last_Pe = None

        for geo in parent.geos:
            if isinstance(geo, LineGeo):
                new_geo = OffLineGeo(geo=geo, parent=parent.parentEntity)
            elif isinstance(geo, ArcGeo):
                new_geo = OffArcGeo(geo=geo, parent=parent.parentEntity)
            else:
                logger.error("Should not be here")

            if last_Pe is not None:
                #                 logger.debug("Current distance: %s" %
                #                              new_geo.Ps.distance(last_Pe))
                if new_geo.Ps.distance(last_Pe) > 0.0:
                    new_geo.match_Ps_to_Pe(last_Pe)

#                     logger.debug("New distance: %s" %
#                                  new_geo.Ps.distance(last_Pe))

            last_Pe = new_geo.Pe

            self.geos.append(new_geo)

        self.make_shape_ccw()
        self.join_colinear_lines()

    def geos_postprocessing(self, min_length):
        """
        Do all the postprocessing required in order to have working sweepline
         algorithm.
        @param min_length: The min_length must be bigger ghen eps, otherwise 
        potential errors may occure.
        """
        #FIXME
        pass
        
        

    def make_segment_types(self):
        """
        This function is called in order to generate the segements according
        to Definiton 2.
        An edge (line) is a linear segment and a reflex vertex is is reflex
        segment. Colinear lines are assumed to be removed prior to the segment
        type definition.
        """
        # Do only if more then 2 geometies
#         if len(self.geos) < 2:
#             return

        # Start with first Vertex if the line is closed
        if self.closed:
            start = 0
        else:
            start = 1
            geo1 = self.geos[0]
            if isinstance(geo1, LineGeo):
                geo1.start_normal = geo1.Ps.get_normal_vector(geo1.Pe)
                geo1.end_normal = geo1.Ps.get_normal_vector(geo1.Pe)
            else:
                geo1.start_normal = geo1.O.unit_vector(geo1.Ps, r=1)
                geo1.end_normal = geo1.O.unit_vector(geo1.Pe, r=1)
                if geo1.ext < 0:
                    geo1.start_normal = geo1.start_normal * -1
                    geo1.end_normal = geo1.end_normal * -1
            self.segments += [geo1]

        for i in range(start, len(self.geos)):
            geo1 = self.geos[i - 1]
            geo2 = self.geos[i]

            if i == start:
                if isinstance(geo1, LineGeo):
                    geo1.start_normal = geo1.Ps.get_normal_vector(geo1.Pe)
                    geo1.end_normal = geo1.Ps.get_normal_vector(geo1.Pe)
                else:
                    geo1.start_normal = geo1.O.unit_vector(geo1.Ps, r=1)
                    geo1.end_normal = geo1.O.unit_vector(geo1.Pe, r=1)
                    if geo1.ext < 0:
                        geo1.start_normal = geo1.start_normal * -1
                        geo1.end_normal = geo1.end_normal * -1

            if isinstance(geo2, LineGeo):
                geo2.start_normal = geo2.Ps.get_normal_vector(geo2.Pe)
                geo2.end_normal = geo2.Ps.get_normal_vector(geo2.Pe)
            elif isinstance(geo2, ArcGeo):
                geo2.start_normal = geo2.O.unit_vector(geo2.Ps, r=1)
                geo2.end_normal = geo2.O.unit_vector(geo2.Pe, r=1)
                if geo2.ext < 0:
                    geo2.start_normal = geo2.start_normal * -1
                    geo2.end_normal = geo2.end_normal * -1
                    
            if ((isinstance(geo2, ArcGeo)) and
                    ((self.offtype == "out" and geo2.ext > 0) or
                     (self.offtype == "in" and geo2.ext < 0)) and
                    ((geo2.r - abs(self.offset)) < -eps)):
                
                #logger.debug("ConvexPoint")

                newgeo2 = ConvexPoint(geo2.O.x, geo2.O.y)
                newgeo2.start_normal = geo2.start_normal
                newgeo2.end_normal = geo2.end_normal
                geo2 = newgeo2

            #logger.debug(geo1.Pe.ccw(geo1.Pe + geo1.end_normal,
            #                  geo1.Pe + geo1.end_normal + 
            #                  geo2.start_normal))

            if (((geo1.Pe.ccw(geo1.Pe + geo1.end_normal,
                              geo1.Pe + geo1.end_normal + 
                              geo2.start_normal) == 1) and
                 self.offtype == "in") or
                (geo1.Pe.ccw(geo1.Pe + geo1.end_normal,
                             geo1.Pe + geo1.end_normal + 
                             geo2.start_normal) == -1 and
                 self.offtype == "out")):

                reflexPe = OffPoint(x=geo1.Pe.x, y=geo1.Pe.y)
                reflexPe.start_normal = geo1.end_normal
                reflexPe.end_normal = geo2.start_normal
                self.segments += [reflexPe, geo2]
                
            elif (geo1.Pe.ccw(geo1.Pe + geo1.end_normal,
                              geo1.Pe + geo1.end_normal + 
                              geo2.start_normal) == 0):
                self.segments += [geo2]

            # Add the linear segment which is a line connecting 2 vertices
            else:
                # A convex vertex (the linear segment of the paper). Its raw
                # offset is the round join around the vertex; it needs the
                # normals of the two incident edges (like the reflex point and
                # the collapsed arc above), otherwise make_rawoff_seg would
                # fail. The LIR removal mitres it later where required.
                convexPe = ConvexPoint(geo1.Pe.x, geo1.Pe.y)
                convexPe.start_normal = geo1.end_normal
                convexPe.end_normal = geo2.start_normal
                self.segments += [convexPe, geo2]
            
    def make_rawoff_seg(self, seg):
        """
        This function returns the rawoffset of a segement. A line for a line
        and a circle for a reflex segement.
        @param segment_nr: The nr of the segement for which the rawoffset
        segement shall be generated
        @ return: Returns the rawoffsetsegement of the  defined segment
        """

        # seg=self.segments[segment_nr]

        if self.offtype == "out":
            offset = -abs(self.offset)
        else:
            offset = abs(self.offset)

        # if segement 1 is inverted change End Point
        if isinstance(seg, OffLineGeo):
            Ps = seg.Ps + seg.start_normal * offset
            Pe = seg.Pe + seg.end_normal * offset

            return OffLineGeo(Ps, Pe)

        elif isinstance(seg, OffPoint):
            Ps = seg + seg.start_normal * offset
            Pe = seg + seg.end_normal * offset

            return OffArcGeo(Ps=Ps, Pe=Pe, O=deepcopy(seg),
                             r=self.offset, direction=offset)
        elif isinstance(seg, OffArcGeo):
            Ps = seg.Ps + seg.start_normal * offset
            Pe = seg.Pe + seg.end_normal * offset

            # logger.debug(seg.Ps)
            # logger.debug(seg.Pe)
            # logger.debug(seg.start_normal)
            # logger.debug(seg.end_normal)                         

            if seg.ext > 0:
                return OffArcGeo(Ps=Ps, Pe=Pe, O=seg.O,
                                 r=seg.r + offset, direction=seg.ext)
            else:
                return OffArcGeo(Ps=Ps, Pe=Pe, O=seg.O,
                                 r=seg.r - offset, direction=seg.ext)    

        elif isinstance(seg, ConvexPoint):
            Ps = seg + seg.start_normal * offset
            Pe = seg + seg.end_normal * offset
            return OffArcGeo(Ps=Ps, Pe=Pe, O=deepcopy(seg),
                             r=self.offset, direction=offset)
        else:
            logger.error("Unsupportet Object type: %s" % type(seg))

    def interfering_full(self, segment1, direction, segment2):
        """
        Check if the Endpoint (dependent on direction) of segment 1 is
        interfering with segment 2 Definition according to Definition 6
        @param segment 1: The first segment
        @param direction: The direction of the line 1, as given -1 reversed
        @param segment 2: The second segment to be checked
        @ return: Returns True or False
        """

#         if isinstance(segment1, ConvexPoint):
#             logger.debug("Should not be here")
#             return False
#         else:
#             offGeo = self.make_rawoff_seg(segment1)
# self.interferingshapes += [offGeo]
#
#         if isinstance(segment1, OffPoint):
#             offGeo = segment1
#         elif direction == 1:
#             offGeo = segment1.Pe
#         elif direction == -1:
#             offGeo = segment1.Ps
# #
# logger.debug(offGeo)
#         logger.debug("Full distance: %s" % segment2.distance(offGeo))
# If the distance from the Line to the Center of the Tangential Circle
# is smaller then the radius we have an intersection
#         return segment2.distance(offGeo) <= abs(self.offset) + eps

        # if segement 1 is inverted change End Point
        if isinstance(segment1, OffLineGeo) and direction == 1:
            Pe = segment1.Pe
        elif isinstance(segment1, OffLineGeo) and direction == -1:
            Pe = segment1.Ps
        elif isinstance(segment1, ConvexPoint):
            return False
        elif isinstance(segment1, OffPoint):
            Pe = segment1
        elif isinstance(segment1, OffArcGeo) and direction == 1:
            Pe = segment1.Pe
        elif isinstance(segment1, OffArcGeo) and direction == -1:
            Pe = segment1.Ps
        else:
            logger.error("Unsupportet Object type: %s" % type(segment1))

        # if we cut outside reverse the offset
        if self.offtype == "out":
            offset = -abs(self.offset)
        else:
            offset = abs(self.offset)

        if direction == 1:
            distance = segment2.distance(Pe + segment1.end_normal * offset)

        else:
            distance = segment2.distance(Pe + segment1.start_normal * offset)

        # logger.debug("Full distance: %s" % distance)

        # If the distance from the Segment to the Center of the Tangential
        # Circle is smaller then the radius we have an intersection
        return distance <= abs(offset) + eps

    def interfering_partly(self, segment1, direction, segment2):
        """
        Check if any tangential circle of segment 1 is interfering with
        segment 2. Definition according to Definition 5
        @param segment 1: The first Line
        @param direction: The direction of the segment 1, as given -1 reversed
        @param segment 2: The second line to be checked
        @ return: Returns True or False
        """
        if isinstance(segment1, ConvexPoint):
            logger.debug("Should not be here")
            logger.debug(segment1)
            return False
            # offGeo = self.make_rawoff_seg(segment1)
            
        else:
            offGeo = self.make_rawoff_seg(segment1)
#
        # logger.debug(offGeo)
        # logger.debug("Partly distance: %s" % segment2.distance(offGeo))
        
        # If the distance from the Line to the Center of the Tangential Circle
        # is smaller then the radius we have an intersection
        return segment2.distance(offGeo) <= abs(self.offset) + eps

    def Interfering_relation(self, segment1, segment2):
        """
        Check the interfering relation between two segements (segment1 and
        segment2). Definition acccording to Definition 6
        @param segment1: The first segment (forward)
        @param segment2: The second segment (backward)
        @return: Returns one of [full, partial, reverse, None] interfering
        relations for both segments
        """
        # Check if segments are equal
        if segment1 == segment2:
            return None, None

        if self.interfering_full(segment1, 1, segment2):
            L1_status = "full"
        elif self.interfering_partly(segment1, 1, segment2):
            L1_status = "partial"
        else:
            L1_status = "reverse"

        if self.interfering_full(segment2, -1, segment1):
            L2_status = "full"
        elif self.interfering_partly(segment2, -1, segment1):
            L2_status = "partial"
        else:
            L2_status = "reverse"

        # logger.debug("Start Status: L1_status: %s,L2_status: %s"
        # % (L1_status, L2_status))

        return [L1_status, L2_status]

    def PairWiseInterferenceDetection(self, forward, backward,):
        """
        Returns the first forward and backward segment nr. for which both
        interfering conditions are partly.
        @param foward: The nr of the first forward segment
        @param backward: the nr. of the first backward segment
        @return: forward, backward
        """
        val = 2000
        logger.debug(len(self.segments))
        # P1: Reset the counter for every interference detection - it is a
        # safety limit for a single walk only and must not accumulate over
        # all convex vertices of the shape (which aborted the whole offset).
        self.counter = 0

        try:
            SPoint=self.segments[forward].Ps
        except AttributeError:
            # Expected case while seeding the GIR walk: the forward element
            # is a vertex placeholder (OffPoint/ConvexPoint) without a Ps
            # attribute. remove_global_interferences() tries both walk
            # directions (i,j) and (j,i) and uses the one that can start;
            # this direction simply cannot. It is NOT an error - keep the
            # walk result None (control flow unchanged).
            logger.debug("Pairwise walk cannot start at segment %s "
                         "(no Ps attribute) - opposite direction is tried",
                         forward)
            return
        except Exception:
            logger.exception("Cannot do cutter compensation, please check "
                             "file / diameter of tool")
            return

        L1_status, L2_status = "full", "full"
        # Repeat until we reached the Partial-interfering-relation
        while not(L1_status == "partial" and L2_status == "partial"):
            self.interferingshapes = []
            self.counter += 1

            if forward >= len(self.segments):
                if not self.closed:
                    # An open contour is not cyclic: the walk must not wrap
                    # around. Reaching the open end means no interference was
                    # found - the caller keeps the raw offset of the vertex.
                    return None, None
                forward = 0

            segment1 = self.segments[forward]
            segment2 = self.segments[backward]
            logger.debug("segment1: %s" % segment1)
            logger.debug("segment2: %s" % segment2)

            if isinstance(segment1, ConvexPoint):
                forward += 1
                if forward >= len(self.segments):
                    if not self.closed:
                        return None, None
                    forward = 0
                segment1 = self.segments[forward]
                logger.debug("Forward ConvexPoint")
            if isinstance(segment2, ConvexPoint):
                backward -= 1
                if backward < 0:
                    if not self.closed:
                        return None, None
                    backward = len(self.segments) - 1
                segment2 = self.segments[backward]

            [L1_status, L2_status] = self.Interfering_relation(
                segment1, segment2)
            logger.debug("Start Status: L1_status: %s,L2_status: %s"
                         % (L1_status, L2_status))

            """
            The reverse interfering segment is replaced  by the first
            non-reverse-interfering segment along it's tracking direction
            """
            if L1_status == "reverse":
                while L1_status == "reverse":
                    self.counter += 1
                    # logger.debug(self.counter)
                    if self.counter > val:
                        break
                    if self.counter >= val:
                        self.interferingshapes = []
                    forward += 1
                    if forward >= len(self.segments):
                        if not self.closed:
                            return None, None
                        forward = 0
                    segment1 = self.segments[forward]

                    if isinstance(segment1, ConvexPoint):
                        forward += 1
                        if forward >= len(self.segments):
                            if not self.closed:
                                return None, None
                            forward = 0
                        segment1 = self.segments[forward]
                        logger.debug("Forward ConvexPoint")

                    logger.debug("Reverse Replace: forward: %s, backward: %s"
                                 % (forward, backward))

                    [L1_status, L2_status] = self.Interfering_relation(
                        segment1, segment2)
                    logger.debug("Checking: forward: %s, backward: %s"
                                 %(forward, backward))
                    logger.debug("Replace Rev.: L1_status: %s,L2_status: %s"
                                 %(L1_status,L2_status))

            elif L2_status == "reverse":
                while L2_status == "reverse":
                    self.counter += 1
                    logger.debug(self.counter)
                    if self.counter > val:
                        break
                    if self.counter >= val:
                        self.interferingshapes = []
                    backward -= 1
                    logger.debug("Reverse Replace: forward: %s, backward: %s"
                                 % (forward, backward))
                    if backward < 0:
                        if not self.closed:
                            return None, None
                        backward = len(self.segments) - 1
                    segment2 = self.segments[backward]

                    if isinstance(segment2, ConvexPoint):
                        backward -= 1
                        if backward < 0:
                            if not self.closed:
                                return None, None
                            backward = len(self.segments) - 1
                        segment2 = self.segments[backward]
                        logger.debug("Backward ConvexPoint")

                    [L1_status, L2_status] = self.Interfering_relation(
                        segment1, segment2)
                    logger.debug("Checking: forward: %s, backward: %s"
                                 % (forward, backward))
                    logger.debug("Replace Rev.: L1_status: %s,L2_status: %s"
                                 % (L1_status, L2_status))

            """
            Full interfering segment is replaced by the nexst segemnt along the
            tracking direction.
            """
            if L1_status == "full" and (L2_status == "partial" or
                                        L2_status == "full"):
                forward += 1
                if forward >= len(self.segments) and not self.closed:
                    return None, None
            elif L2_status == "full" and (L1_status == "partial" or
                                          L1_status == "partial"):
                backward -= 1
                if backward < 0 and not self.closed:
                    return None, None

            # If The begin end point is the end end point we are done.
            if L1_status is None and L2_status is None:
                logger.debug("Begin = End; Remove all; SPoint: %s", SPoint)
                return len(self.segments) - 1, 0

            logger.debug(self.counter)
            logger.debug("L1_status: %s,L2_status: %s" %(L1_status,L2_status))
            if self.counter == val:
                self.interferingshapes = []

            if self.counter > val:  # 26:
                logger.error("No partial - partial status found")
                return None, None

        # logger.debug("Result: forward: %s, backward: %s"
        # %(forward, backward))
        return forward, backward

    def remove_LIR(self, forward, backward, iPoint):
        """
        The instance is used to remove the LIR from the PS curve.
        @param forward: The forward segment of the LIR
        @param backward: The backward segement of the LIR
        @param iPoint: The Intersection point of the LIR
        """
        if backward > forward:
            pop_range = self.segments[backward + 1:len(self.segments)]
            pop_range += self.segments[0:forward]
        elif backward < 0:
            pop_range = self.segments[
                len(self.segments) + backward + 1:len(self.segments)]
            pop_range += self.segments[0:forward]
        else:
            pop_range = self.segments[backward + 1:forward]

        # P2: A corner cut at a convex vertex always removes the
        # ConvexPoint placeholder of that vertex - that is normal and does
        # NOT split the loop. Only removals which ate real geometry (a
        # whole feature/region) mark a pinch point where separate milling
        # loops may be split.
        removed_real = [x for x in pop_range
                        if not isinstance(x, ConvexPoint)]
        if len(removed_real) > 0:
            self.split_cips.append(iPoint)

        if self.offtype == "out":
            rev = True
        else:
            rev = False
        # Modify the first segment and the last segment of the LIR
        self.segments[forward] = self.segments[
            forward].trim(Point=iPoint, dir=1, rev_norm=rev)
        self.segments[backward] = self.segments[
            backward].trim(Point=iPoint, dir=-1, rev_norm=rev)

        # Remove the segments which are inbetween the LIR
        self.segments = Geos([x for x in self.segments if x not in pop_range])

    def remove_global_interferences(self):
        """
        GIR removal per Choi & Park (1999), global interference section.

        After the LIR removal the raw offset curve may still self-intersect
        (global interferences). Every self-intersection point seeds the
        existing, UNCHANGED PairWiseInterferenceDetection: its walk yields
        the neighbouring contact pair - the opposite boundary of the same
        interference. The cyclic region between seed and contact
        (GIR = [f_s, f_e] U [b_e, b_s]) is collected; ALL GIRs are
        collected before any geometry is modified (delayed removal), so
        overlapping regions cannot corrupt each other.

        rawoff[k] corresponds 1:1 to segments[k] (make_rawoff_seg creates
        exactly one offset geometry per segment), so the walk can be seeded
        with raw-offset indices directly.
        """
        n = len(self.rawoff)
        if n < 3:
            return

        # --- Step 1: self-intersections of the raw offset curve ----------
        # _find_crossings() checks all non-adjacent (cyclic) pairs with the
        # production intersection routine and deduplicates by location.
        seeds = self._find_crossings(self.rawoff)

        # --- Steps 2-5: seed walks, collect GIRs (no geometry changes) ---
        girs = []
        marked = set()
        skipped = 0

        def key_of(a, b):
            return (min(a, b), max(a, b))

        for (i, j, X_seed) in seeds:
            if key_of(i, j) in marked:
                continue

            # Step 2: forward/backward directions - exactly one of the two
            # assignments yields a walk that does not stop at the seed
            # (the other is either degenerate [partial,partial] at the
            # crossing or cannot start because its forward element is an
            # OffPoint without a Ps attribute).
            accepted = None
            for (a, b) in ((i, j), (j, i)):
                self.counter = 0
                try:
                    res = self.PairWiseInterferenceDetection(a, b)
                except Exception:
                    logger.exception("GIR seed walk failed for (%i,%i)", i, j)
                    continue
                if not (isinstance(res, tuple) and res[0] is not None):
                    continue
                f_e, b_e = res[0], res[1]
                if f_e == a and b_e == b:
                    # walk stopped immediately at the seed - degenerate
                    continue
                accepted = (a, b, f_e, b_e)
                break

            if accepted is None:
                skipped += 1
                logger.warning(
                    "GIR: no valid walk from self-intersection (%i,%i) - "
                    "seed skipped (if it is a boundary of an interference, "
                    "the walk of the opposite boundary covers it)", i, j)
                continue

            f_s, b_s, f_e, b_e = accepted

            # Step 3/4: the walk contact must be a real intersection of its
            # two elements - never invent GIR endpoints.
            X_end = self.rawoff[f_e].find_inter_point(self.rawoff[b_e])
            if X_end is None:
                skipped += 1
                logger.warning(
                    "GIR: walk from (%i,%i) ended at (%i,%i) without an "
                    "intersection point - seed skipped", i, j, f_e, b_e)
                continue
            if isinstance(X_end, list):
                # several intersections: deterministic, geometry based
                # choice - the one nearest to the seed point
                X_end = min(X_end, key=lambda P: P.distance(X_seed))

            # The raw offset of a closed contour is closed: its first and
            # last element share the connection point. The pairwise walk
            # stops there because adjacent elements have distance 0 - that is
            # NOT a self-intersection. Only this shared connection is
            # skipped; a real crossing of the same two elements at another
            # point (then the seed is at that crossing) is still processed.
            n_raw = len(self.rawoff)
            is_connection = (
                (f_e == n_raw - 1 and b_e == 0) or
                (f_e == 0 and b_e == n_raw - 1))
            if self.closed and is_connection:
                connection = self.rawoff[0].Ps
                if (X_end.distance(connection) <= eps * 10 and
                        X_seed.distance(connection) > eps * 10):
                    skipped += 1
                    logger.debug(
                        "GIR: contact is the cyclic connection of the closed "
                        "raw offset - skipped")
                    continue

            # sanity: the two cyclic intervals must be well defined. The
            # observed special cases (walk ends on the same element it
            # started from):
            # - f_s == f_e: interval A lies WITHIN the element f_s
            # - b_e == b_s: interval B lies WITHIN the element b_s
            # In the paper's continuous parameterization [f_s, f_e] resp.
            # [b_e, b_s] then cover a part of that element between the two
            # crossing points. Any other coincident boundaries are
            # ill-defined and skipped.
            vals = (f_s, b_s, f_e, b_e)
            bad = False
            for x in range(4):
                for y in range(x + 1, 4):
                    if vals[x] == vals[y] and {x, y} not in ({0, 2}, {1, 3}):
                        bad = True
            if bad:
                skipped += 1
                logger.warning(
                    "GIR: degenerate boundary set (%i,%i,%i,%i) - skipped",
                    f_s, b_s, f_e, b_e)
                continue

            girs.append((f_s, b_s, f_e, b_e, X_seed, X_end))
            # Step 4: mark BOTH boundaries so the same interference is not
            # processed twice
            marked.add(key_of(i, j))
            marked.add(key_of(f_e, b_e))
            logger.debug("GIR collected: seed (%i,%i) -> contact (%i,%i)",
                         f_s, b_s, f_e, b_e)

        # --- Step 6: delayed removal of all collected GIRs ---------------
        if girs:
            self._remove_girs(girs)
        if skipped:
            logger.debug("GIR: %i seed(s) skipped", skipped)

    def _remove_girs(self, girs):
        """
        Remove the collected global interference regions (paper step 6).

        For every GIR the two cyclic intervals [f_s..f_e] and [b_e..b_s]:
        - all elements strictly inside the intervals are deleted,
        - the boundary elements are trimmed at their crossing points:
          on a boundary element the interference removes the part that the
          interval covers, the rest is kept. On different elements this is
          the classic convention (interval start keeps [Ps..X], interval
          end keeps [X..Pe]); the cut ends of an interval meet each other
          exactly at the crossing point, so the remaining curve closes
          without artificial gaps.

        Same-element intervals (f_s == f_e or b_e == b_s): the interference
        boundary lies WITHIN one element, between the two crossing points.
        Then the covered part is the sub-segment from the interval start
        crossing forward to its end crossing (along Ps -> Pe, wrapping at
        the element ends); the valid remainder (complement within the
        element, possibly two pieces for a line or an arc) is kept. This
        is why cyc_range(a, a) must yield NO strictly-inside element: the
        interval lives inside a single element, so nothing between two
        distinct elements is deleted.

        All GIRs are collected before any geometry is touched, and the
        removed sub-intervals per element are merged, so several GIRs on
        the same element never use stale parameters or trim twice.

        The trimmed geometries are raw-offset lines/arcs (OffLineGeo /
        OffArcGeo); OffPoint elements have no trim method, but their raw
        offset is an OffArcGeo, which is trimmed here.
        """
        n = len(self.rawoff)

        def cyc_range(a, b):
            """Indices strictly between a and b, cyclic forward (a -> b).
            Empty when a == b (within-element interval)."""
            out = []
            if a == b:
                return out
            k = (a + 1) % n
            while k != b:
                out.append(k)
                k = (k + 1) % n
            return out

        deletes = set()
        removed_ivs = {}   # idx -> list of (t0, t1) removed along Ps->Pe

        def add_iv(idx, a, b):
            if a is None or b is None:
                return
            a, b = max(0.0, min(1.0, a)), max(0.0, min(1.0, b))
            if b - a > 1e-9:
                removed_ivs.setdefault(idx, []).append((a, b))

        def add_iv_forward(idx, ta, tb):
            """Remove the forward sub-segment ta -> tb (wraps if ta > tb)."""
            if ta is None or tb is None:
                return
            if ta <= tb:
                add_iv(idx, ta, tb)
            else:
                add_iv(idx, ta, 1.0)
                add_iv(idx, 0.0, tb)

        for (f_s, b_s, f_e, b_e, X_P, X_Q) in girs:
            # strictly-inside elements (empty for same-element intervals)
            for k in cyc_range(f_s, f_e):
                deletes.add(k)
            for k in cyc_range(b_e, b_s):
                deletes.add(k)

            # forward interval A: start f_s, end f_e
            if f_s == f_e:
                g = self.rawoff[f_s]
                add_iv_forward(f_s, self._geo_param(g, X_P),
                               self._geo_param(g, X_Q))
            else:
                add_iv(f_s, self._geo_param(self.rawoff[f_s], X_P), 1.0)
                add_iv(f_e, 0.0, self._geo_param(self.rawoff[f_e], X_Q))

            # backward interval B: start b_e, end b_s
            if b_e == b_s:
                g = self.rawoff[b_s]
                add_iv_forward(b_s, self._geo_param(g, X_Q),
                               self._geo_param(g, X_P))
            else:
                add_iv(b_e, self._geo_param(self.rawoff[b_e], X_Q), 1.0)
                add_iv(b_s, 0.0, self._geo_param(self.rawoff[b_s], X_P))

        # apply: delete first, then keep the valid remainder of the rest
        new_rawoff = []
        removed = 0
        for k, geo in enumerate(self.rawoff):
            if k in deletes:
                removed += 1
                continue
            if k in removed_ivs:
                pieces = self._kept_pieces(geo, removed_ivs[k])
                added = 0
                for p in pieces:
                    if getattr(p, 'length', 0.0) > eps * 10:
                        new_rawoff.append(p)
                        added += 1
                if added == 0:
                    # degenerate rest - drop it; its neighbours meet at
                    # the same crossing point anyway
                    removed += 1
            else:
                new_rawoff.append(geo)

        self.rawoff = self._reconnect_rawoff(new_rawoff)
        logger.debug("GIR removal: %i element(s) removed", removed)

    def _reconnect_rawoff(self, pieces, tol=None):
        """
        Re-order the raw-offset pieces so that the curve stays continuous:
        a piece whose Ps coincides with the Pe of another piece is placed
        directly after it (re-connection exactly at the GIR crossing
        points).

        When several GIRs cut the SAME element, the valid remainder can
        start/end at crossing points of DIFFERENT interferences; in the
        original element order its true neighbours are the trimmed
        boundary elements of those interferences, which are NOT adjacent in
        the sequence. A plain (index) ordering then leaves an orphaned
        fragment. Following the geometric continuity (Pe == next.Ps)
        re-joins such pieces into their proper chains - the removal of all
        GIRs is thereby applied jointly, never per GIR.

        Pieces without a partner keep their relative order; they are
        genuine free fragments (handled later by split_into_loops).
        """
        if tol is None:
            tol = eps * 10
        pieces = list(pieces)
        n = len(pieces)
        if n <= 2:
            return pieces
        used = [False] * n
        order = []
        for s in range(n):
            if used[s]:
                continue
            used[s] = True
            order.append(s)
            cur = s
            while True:
                nxt = None
                for j in range(n):
                    if not used[j] and pieces[cur].Pe.distance(pieces[j].Ps) <= tol:
                        nxt = j
                        break
                if nxt is None:
                    break
                used[nxt] = True
                order.append(nxt)
                cur = nxt
        return [pieces[i] for i in order]

    def _geo_param(self, geo, X):
        """
        Parameter 0..1 of point X along a raw offset geometry (Ps -> Pe).
        For arcs the angle fraction along ext is used, so the direction is
        respected. Returns None when undefined (degenerate element).
        """
        try:
            if isinstance(geo, ArcGeo):
                if abs(geo.ext) < eps:
                    return None
                return geo.dif_ang(geo.Ps, X, geo.ext) / geo.ext
            L = geo.Ps.distance(geo.Pe)
            if L < eps:
                return None
            return geo.Ps.distance(X) / L
        except Exception:
            logger.exception("GIR: parameter of a crossing not determinable")
            return None

    def _sub_geo(self, geo, t0, t1):
        """
        Sub-geometry of a raw offset geometry for the parameter range
        [t0, t1] along Ps -> Pe. Arcs keep center, radius and direction.
        Returns None for a degenerate range.
        """
        t0 = max(0.0, min(1.0, t0))
        t1 = max(0.0, min(1.0, t1))
        if t1 - t0 <= 1e-12:
            return None
        if isinstance(geo, ArcGeo):
            a0 = geo.s_ang + geo.ext * t0
            a1 = geo.s_ang + geo.ext * t1
            return OffArcGeo(Ps=geo.O.get_arc_point(a0, r=geo.r),
                             Pe=geo.O.get_arc_point(a1, r=geo.r),
                             O=geo.O, r=geo.r,
                             direction=(1 if geo.ext >= 0 else -1))
        P0 = Point(geo.Ps.x + (geo.Pe.x - geo.Ps.x) * t0,
                   geo.Ps.y + (geo.Pe.y - geo.Ps.y) * t0)
        P1 = Point(geo.Ps.x + (geo.Pe.x - geo.Ps.x) * t1,
                   geo.Ps.y + (geo.Pe.y - geo.Ps.y) * t1)
        return OffLineGeo(P0, P1)

    def _kept_pieces(self, geo, removed):
        """
        The parts of geo (parameter 0..1) NOT covered by the removed
        intervals (complement within the element, merged and ordered).
        """
        ivs = sorted((max(0.0, a), min(1.0, b)) for a, b in removed
                     if b - a > 1e-12)
        merged = []
        for a, b in ivs:
            if merged and a <= merged[-1][1] + 1e-9:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        pieces = []
        cur = 0.0
        for a, b in merged:
            if a - cur > 1e-9:
                p = self._sub_geo(geo, cur, a)
                if p is not None:
                    pieces.append(p)
            cur = max(cur, b)
        if 1.0 - cur > 1e-9:
            p = self._sub_geo(geo, cur, 1.0)
            if p is not None:
                pieces.append(p)
        return pieces

    def _loop_signed_area(self, geos):
        """
        Signed area of a closed geo sequence (shoelace formula over sampled
        points). Arcs are subdivided so the value is exact enough for a
        sign check.
        """
        pts = []
        for geo in geos:
            if isinstance(geo, ArcGeo):
                steps = max(2, int(abs(geo.ext) / (pi / 18.0)))
                for s in range(steps + 1):
                    ang = geo.s_ang + geo.ext * s / float(steps)
                    pts.append(Point(geo.O.x + cos(ang) * geo.r,
                                     geo.O.y + sin(ang) * geo.r))
            else:
                pts.append(geo.Ps)

        area = 0.0
        m = len(pts)
        for k in range(m):
            p1 = pts[k]
            p2 = pts[(k + 1) % m]
            area += p1.x * p2.y - p2.x * p1.y
        return area / 2.0

    def _loop_area_sign_ok(self, geos, ref_sign):
        """
        Check the winding of the loop: valid offset loops have the same
        orientation sign as the original (preprocessed) contour; wrongly
        wound loops are gouging islands and must be discarded.
        """
        return (self._loop_signed_area(geos) * ref_sign) > 0.0

    def _loop_big_enough(self, geos):
        """
        Sliver check: discard loops with a negligible area (e.g. from
        tangential near-crossings).
        """
        return abs(self._loop_signed_area(geos)) >= min_length * min_length

    def _find_crossings(self, geos):
        """
        Find all self-intersection points of a closed geo sequence.
        Returns a list of (i, j, X) tuples: i < j, non-adjacent pairs,
        deduplicated by location.
        """
        n = len(geos)
        # Broad-phase filter: two geometries can only intersect if their
        # bounding boxes overlap, so precompute one box per geometry (the full
        # circle box for arcs) and skip the expensive exact intersection test
        # for the (usually many) pairs that cannot cross. The result is
        # identical - this only avoids work that could never contribute a
        # crossing.
        boxes = []
        for geo in geos:
            if isinstance(geo, LineGeo):
                ax, bx = geo.Ps.x, geo.Pe.x
                ay, by = geo.Ps.y, geo.Pe.y
                if ax > bx:
                    ax, bx = bx, ax
                if ay > by:
                    ay, by = by, ay
                boxes.append((ax, bx, ay, by))
            elif isinstance(geo, ArcGeo):
                o = geo.O
                boxes.append((o.x - geo.r, o.x + geo.r,
                              o.y - geo.r, o.y + geo.r))
            else:
                boxes.append(None)

        crossings = []
        for i in range(n):
            box_i = boxes[i]
            geo_i = geos[i]
            for j in range(i + 1, n):
                # Adjacent geometries share an endpoint by construction
                if j - i == 1 or (i == 0 and j == n - 1):
                    continue
                box_j = boxes[j]
                if box_i is not None and box_j is not None:
                    if (box_j[0] > box_i[1] + eps or box_j[1] < box_i[0] - eps or
                            box_j[2] > box_i[3] + eps or box_j[3] < box_i[2] - eps):
                        continue
                try:
                    P = geo_i.find_inter_point(geos[j])
                except Exception:
                    logger.exception("Intersection search failed for "
                                     "geometries %i and %i" % (i, j))
                    continue
                if P is None:
                    continue
                for X in (P if isinstance(P, list) else [P]):
                    crossings.append((i, j, X))

        # Deduplicate crossings at the same location
        unique = []
        for c in crossings:
            if all(c[2].distance(u[2]) > eps * 10 for u in unique):
                unique.append(c)
        return unique

    def _split_geo_at(self, geo, X, tol):
        """
        Split a raw offset geometry at the point X lying on it.
        Returns [part1, part2] or [geo] if X is not inside the geometry
        (X at an endpoint or off the geometry).
        """
        if isinstance(geo, OffLineGeo) or isinstance(geo, LineGeo):
            d_sum = geo.Ps.distance(X) + X.distance(geo.Pe)
            d_tot = geo.Ps.distance(geo.Pe)
            if d_sum - d_tot > tol:
                return [geo]   # X not on the segment
            if geo.Ps.distance(X) <= tol or X.distance(geo.Pe) <= tol:
                return [geo]   # X at an endpoint - no split needed
            return [OffLineGeo(geo.Ps, X), OffLineGeo(X, geo.Pe)]
        elif isinstance(geo, OffArcGeo) or isinstance(geo, ArcGeo):
            if (abs(geo.O.distance(X) - geo.r) > tol or
                    not geo.PointAng_withinArc(X)):
                return [geo]
            if geo.Ps.distance(X) <= tol or X.distance(geo.Pe) <= tol:
                return [geo]   # X at an endpoint - no split needed
            return geo.split_into_2geos(ipoint=X)
        return [geo]

    def _split_at_crossing(self, geos, i, j, gi_parts, gj_parts, X, tol):
        """
        Split the closed geo sequence at the crossing X (lying on geos i
        and j). Returns (loop1, loop2) - both closed chains through X -
        or None if the crossing cannot be resolved.
        """
        n = len(geos)
        expanded = []
        joints = []
        for k in range(n):
            if k == i:
                parts = gi_parts
            elif k == j:
                parts = gj_parts
            else:
                # X does not lie on this geometry - no joint entry
                expanded.append(geos[k])
                continue

            if len(parts) == 2:
                # X inside the geometry: joint between the two parts
                joints.append(len(expanded) + 1)
                expanded += parts
            else:
                gk = parts[0]
                if X.distance(gk.Ps) <= tol:
                    joints.append(len(expanded))
                elif X.distance(gk.Pe) <= tol:
                    joints.append(len(expanded) + 1)
                else:
                    joints.append(None)   # split failed
                expanded += parts

        if None in joints or len(joints) != 2:
            return None

        p_a, p_b = sorted(joints)
        loop1 = expanded[p_a:p_b]
        loop2 = expanded[p_b:] + expanded[:p_a]
        return loop1, loop2

    def _split_loops_recursive(self, geos, ref_sign, depth=0):
        """
        Recursive splitting of a closed curve at its self-intersection
        points. At each crossing the curve is split into two closed loops;
        the wrongly wound one (gouging island) is discarded via the signed
        area check relative to the original contour orientation. The other
        loop may still contain crossings and is handled recursively.
        Returns a list of valid loops.
        """
        if not geos:
            return []
        if depth > 50:
            logger.warning("Loop splitting: recursion limit reached - "
                           "keeping the loop as it is")
            if (self._loop_area_sign_ok(geos, ref_sign) and
                    self._loop_big_enough(geos)):
                return [geos]
            return []

        crossings = self._find_crossings(geos)
        if not crossings:
            # Simple closed curve without crossings: offsets preserve the
            # orientation, so the size check is sufficient here - the
            # winding check stays reserved for the actual split decision.
            if self._loop_big_enough(geos):
                return [geos]
            return []

        # Smallest span first (local ears are resolved first)
        crossings.sort(key=lambda c: c[1] - c[0])

        split = None
        tol = eps * 10
        for (i, j, X) in crossings:
            gi_parts = self._split_geo_at(geos[i], X, tol)
            gj_parts = self._split_geo_at(geos[j], X, tol)
            split = self._split_at_crossing(geos, i, j, gi_parts, gj_parts,
                                            X, tol)
            if split is not None:
                break

        if split is None:
            logger.warning("Loop splitting: crossings could not be "
                           "resolved - keeping the loop as it is")
            if self._loop_big_enough(geos):
                return [geos]
            return []

        loop1, loop2 = split
        loops = []
        for part in (loop1, loop2):
            if not part:
                continue
            if not self._loop_area_sign_ok(part, ref_sign):
                logger.debug("Loop splitting: discarding gouging island "
                             "(wrong winding)")
                continue
            if not self._loop_big_enough(part):
                logger.debug("Loop splitting: discarding too small loop")
                continue
            loops += self._split_loops_recursive(part, ref_sign, depth + 1)
        return loops

    def split_into_loops(self, tol=None):
        """
        P2: Split the raw offset curve into separate loops.

        Level 1 cuts the sequence where consecutive raw offset geometries
        are not connected (gaps left by the gouging removal). Pinch
        points (split_cips) are NOT cut here: after the LIR removal the
        curve passes through them CONNECTED, and after a successful trim
        both loop ends meet there - cutting would re-open just-closed
        loops. Level 2 (genuinely closed chains only) splits each closed
        chain at its remaining self-intersection points; the wrongly
        wound loops (gouging islands) are discarded via the signed area
        check relative to the original contour orientation. The
        remaining loops are milled as separate paths, connected by rapid
        moves.

        @param tol: Connectivity tolerance (defaults to eps * 10)
        """
        if tol is None:
            tol = eps * 10

        self.loops = []
        n = len(self.rawoff)
        if n == 0:
            return

        # --- Level 1: cut the sequence where connections are broken ---
        # (gaps left by the gouging removal). Pinch points (split_cips)
        # are NOT cut here: after the LIR removal the curve passes
        # through them CONNECTED, and after a successful trim both loop
        # ends meet there - cutting would re-open just-closed loops.
        split_at = set()
        for j in range(n):
            junction = self.rawoff[j].Pe
            nxt = self.rawoff[(j + 1) % n].Ps
            if junction.distance(nxt) > tol:
                split_at.add(j)

        if not split_at:
            chains = [list(self.rawoff)]
        else:
            start_j = min(split_at)
            chains = []
            current = []
            for k in range(n):
                idx = (start_j + 1 + k) % n
                geo = self.rawoff[idx]
                j_prev = (start_j + k) % n
                if k > 0 and j_prev in split_at:
                    chains.append(current)
                    current = []
                current.append(geo)
            if current:
                chains.append(current)

        # --- Level 2: split closed chains at their self-intersections ---
        # Only GENUINELY closed chains are eligible: the recursion closes
        # loops through the crossing point. Feeding an open chain would
        # wrap its free ends together - a straight cut across the region.
        # Open chains (fragments left by removals/trims) are kept as they
        # are: safe, connected toolpaths with free ends (rapid moves to
        # the next loop), exactly like the previous behaviour.
        self.loops = []
        ref_sign = 1.0 if self._loop_signed_area(self.geos) >= 0.0 else -1.0
        for chain in chains:
            if len(chain) < 2:
                self.loops.append(chain)
                continue
            end_gap = chain[0].Ps.distance(chain[-1].Pe)
            if end_gap <= tol:
                self.loops += self._split_loops_recursive(chain, ref_sign)
            elif (self.closed and
                  end_gap <= 2 * abs(self.offset) + tol):
                # P2c: The chain ends at a pinch (e.g. a fully removed
                # corridor whose walls the cutter touches simultaneously):
                # pulling both endpoints to the midpoint CLOSES the contour
                # without milling over any material - unlike the generic
                # wrap, this is limited to endpoints within the cutter's
                # simultaneous reach.
                mid = Point((chain[0].Ps.x + chain[-1].Pe.x) / 2.0,
                            (chain[0].Ps.y + chain[-1].Pe.y) / 2.0)
                chain[0].match_Ps_to_Pe(mid)
                chain[-1].match_Pe_to_Ps(mid)
                logger.debug("Loop splitting: closed an open chain by "
                             "pinch (end gap %.4f <= 2*offset)" % end_gap)
                self.loops += self._split_loops_recursive(chain, ref_sign)
            else:
                self.loops.append(chain)


class OffArcGeo(ArcGeo):

    """
    Inherited Class for Shapeoffset only. All related offset functions
    are concentrated here in orde to keep base classes as clean as possible.
    """

    def __init__(self, Ps=None, Pe=None, O=None, r=1,
                 s_ang=None, e_ang=None, direction=1, drag=False, **kwargs):
        """
        Standard Method to initialize the ArcGeo. Not all of the parameters are
        required to fully define a arc. eg. Ps and Pe may be given or s_ang and
        e_ang
        @param Ps: The Start Point of the arc
        @param Pe: the End Point of the arc
        @param O: The center of the arc
        @param r: The radius of the arc
        @param s_ang: The Start Angle of the arc
        @param e_ang: the End Angle of the arc
        @param direction: The arc direction where 1 is in positive direction
        """

        if ("geo" in kwargs) and ("parent" in kwargs):
            geo = kwargs["geo"]
            parent = kwargs["parent"]

            Ps = geo.Ps.rot_sca_abs(parent=parent)
            Pe = geo.Pe.rot_sca_abs(parent=parent)
            O = geo.O.rot_sca_abs(parent=parent)
            r = geo.scaled_r(geo.r, parent)

            direction = 1 if geo.ext > 0.0 else -1

            if parent is not None and parent.sca[0] * parent.sca[1] < 0.0:
                direction *= -1

        ArcGeo.__init__(self, Ps=Ps, Pe=Pe, O=O, r=r,
                        s_ang=s_ang, e_ang=e_ang,
                        direction=direction, drag=drag)

    def distance(self, other):
        """
        Find the distance between 2 geometry elements. Possible is LineGeo
        and ArcGeo
        @param other: the instance of the 2nd geometry element.
        @return: The distance between the two geometries
        """
        """
        Find the distance between 2 geometry elements. Possible is Point,
        LineGeo and ArcGeo
        @param other: the instance of the 2nd geometry element.
        @return: The distance between the two geometries
        """

        if isinstance(other, LineGeo):
            return other.distance_l_a(self)
        elif isinstance(other, Point):
            return self.distance_a_p(other)
        elif isinstance(other, ArcGeo):
            return self.distance_a_a(other)
        else:
            logger.error(
                self.tr("Unsupported geometry type: %s" % type(other)))

    def distance_a_a(self, other):
        """
        Find the distance between two arcs
        @param other: the instance of the 2nd geometry element.
        @return: The distance between the two geometries
        """
        # logger.error('Unsupported function')
        Pself = self.get_nearest_point(other)
        Pother = other.get_nearest_point(self)
        return Pself.distance(Pother)

    def find_inter_point(self, other=[], typ='TIP'):
        """
        Find the intersection between 2 geometry elements.
        Possible is CCLineGeo and ArcGeo
        @param other: the instance of the 2nd geometry element.
        @param typ: Can be "TIP" for True Intersection Point or "Ray" for
        Intersection which is in Ray (of Line)
        @return: a list of intersection points.
        """
        if isinstance(other, LineGeo):
            IPoints = other.find_inter_point_l_a(self, typ)
            return IPoints
        elif isinstance(other, ArcGeo):
            return self.find_inter_point_a_a(other, typ)
        else:
            logger.error("Unsupported Instance: %s" % other.type)

    def find_inter_point_a_a(self, other, typ='TIP'):
        """
        Find the intersection between 2 ArcGeo elements. There can be only one
        intersection between 2 lines.
        @param other: the instance of the 2nd geometry element.
        @param typ: Can be "TIP" for True Intersection Point or "Ray" for
        Intersection which is in Ray (of Line)
        @return: a list of intersection points.
        """

        if typ == "TIP" and self.Ps.distance(other.Pe) < eps * 5:
            return other.Pe
        elif typ == "TIP" and self.Pe.distance(other.Ps) < eps * 5:
            return other.Ps


        O_dis = self.O.distance(other.O)


        # logger.debug(self.Ps.distance(other.Pe))
        # logger.debug(self.Pe.distance(other.Ps))
        # logger.debug(O_dis)

        # If self circle is surrounded by the other no intersection
        if(O_dis < abs(self.r - other.r)):
            return None

        # If other circle is surrounded by the self no intersection
        if(O_dis < abs(other.r - self.r)):
            return None

        # If The circles are to far away from each other no intersection
        # possible
        if (O_dis > abs(other.r + self.r)):
            return None

        # If both circles have the same center and radius
        if abs(O_dis) == 0.0 and abs(self.r - other.r) == 0.0:
            Pi1 = Point(x=self.Ps.x, y=self.Ps.y)
            Pi2 = Point(x=self.Pe.x, y=self.Pe.y)

            logger.debug("Both circels have the same center and radius")
            return [Pi1, Pi2]
        # The following algorithm was found on :
        # http://www.sonoma.edu/users/w/wilsonst/Papers/Geometry/circles/default.htm

        root = ((pow(self.r + other.r, 2) - pow(O_dis, 2)) * 
                (pow(O_dis, 2) - pow(other.r - self.r, 2)))

        # If the Line is a tangent the root is 0.0.
        if root <= 0.0:
            root = 0.0
        else:
            root = sqrt(root)

        xbase = (other.O.x + self.O.x) / 2 + \
            (other.O.x - self.O.x) * \
            (pow(self.r, 2) - pow(other.r, 2)) / (2 * pow(O_dis, 2))

        ybase = (other.O.y + self.O.y) / 2 + \
            (other.O.y - self.O.y) * \
            (pow(self.r, 2) - pow(other.r, 2)) / (2 * pow(O_dis, 2))

        Pi1 = Point(x=xbase + (other.O.y - self.O.y) / 
                    (2 * pow(O_dis, 2)) * root,
                    y=ybase - (other.O.x - self.O.x) / 
                    (2 * pow(O_dis, 2)) * root)

        Pi1_v1 = self.dif_ang(self.Ps, Pi1, self.ext) / self.ext
        Pi1_v2 = other.dif_ang(other.Ps, Pi1, other.ext) / other.ext

        Pi2 = Point(x=xbase - (other.O.y - self.O.y) / 
                    (2 * pow(O_dis, 2)) * root,
                    y=ybase + (other.O.x - self.O.x) / 
                    (2 * pow(O_dis, 2)) * root)

        Pi2_v1 = self.dif_ang(self.Ps, Pi2, self.ext) / self.ext
        Pi2_v2 = other.dif_ang(other.Ps, Pi2, other.ext) / other.ext

        if typ == 'TIP':
            if ((Pi1_v1 >= 0.0 and Pi1_v1 <= 1.0 and
                 Pi1_v2 > 0.0 and Pi1_v2 <= 1.0) and
                    (Pi2_v1 >= 0.0 and Pi2_v1 <= 1.0 and
                     Pi2_v2 > 0.0 and Pi2_v2 <= 1.0)):
                if (root == 0):
                    return Pi1
                else:
                    return [Pi1, Pi2]
                logger.debug("2 Solutions found for TIP")
            elif (Pi1_v1 >= 0.0 and Pi1_v1 <= 1.0 and
                  Pi1_v2 > 0.0 and Pi1_v2 <= 1.0):
                return Pi1
            elif (Pi2_v1 >= 0.0 and Pi2_v1 <= 1.0 and
                  Pi2_v2 > 0.0 and Pi2_v2 <= 1.0):
                return Pi2
            else:
                return None
        elif typ == "Ray":
            # If the root is zero only one solution and the line is a tangent.
            if root == 0:
                return Pi1
            else:
                return [Pi1, Pi2]
        else:
            logger.error("We should not be here")

    def get_nearest_point(self, other):
        """
        Get the nearest point on the arc to another geometry.
        @param other: The Line to be nearest to
        @return: The point which is the nearest to other
        """
        if isinstance(other, LineGeo):
            return other.get_nearest_point_l_a(self, ret="arc")
        elif isinstance(other, ArcGeo):
            return self.get_nearest_point_a_a(other)
        elif isinstance(other, Point):
            return self.get_nearest_point_a_p(other)
        else:
            logger.error("Unsupported Instance: %s" % other.type)

    def get_nearest_point_a_p(self, other):
        """
        Get the nearest point to a point lieing on the arc
        @param other: The Point to be nearest to
        @return: The point which is the nearest to other
        """
        if self.intersect(other):
            return other

        PPoint = self.O.get_arc_point(self.O.norm_angle(other), r=self.r)
        if self.intersect(PPoint):
            return PPoint
        elif self.Ps.distance(other) < self.Pe.distance(other):
            return self.Ps
        else:
            return self.Pe

    def get_nearest_point_a_a(self, other):
        """
        Get the nearest point to a line lieing on the line
        @param other: The Point to be nearest to
        @return: The point which is the nearest to other
        """

        if self.intersect(other):
            return self.find_inter_point_a_a(other)

        # If Nearest point is on both Arc Segments.
        if (other.PointAng_withinArc(self.O) and
                self.PointAng_withinArc(other.O)):
            return self.O.get_arc_point(self.O.norm_angle(other.O),
                                        r=self.r)

        # If Nearest point is at one of the start/end points
        else:
            dismin = self.Ps.distance(other)
            retpoint = self.Ps

            newdis = self.Pe.distance(other)
            if newdis < dismin:
                dismin = newdis
                retpoint = self.Pe

            newdis = other.Ps.distance(self)
            if newdis < dismin:
                dismin = newdis
                retpoint = self.get_nearest_point_a_p(other.Ps)

            newdis = other.Pe.distance(self)
            if newdis < dismin:
                dismin = newdis
                retpoint = self.get_nearest_point_a_p(other.Pe)
            return retpoint

    def intersect(self, other):
        """
        Check if there is an intersection of two geometry elements
        @param, a second geometry which shall be checked for intersection
        @return: True if there is an intersection
        """
        # Do a raw check first with BoundingBox
        # logger.debug("self: %s, \nother: %s, \nintersect: %s"
        # %(self,other,self.BB.hasintersection(other.BB)))
        # logger.debug("self.BB: %s \nother.BB: %s")

        # We need to test Point first cause it has no BB
        if isinstance(other, Point):
            return self.intersect_a_p(other)
        elif not(self.BB.hasintersection(other.BB)):
            return False
        elif isinstance(other, LineGeo):
            return other.intersect_l_a(self)
        elif isinstance(other, ArcGeo):
            return self.intersect_a_a(other)
        else:
            logger.error("Unsupported Instance: %s" % other.type)

    def intersect_a_a(self, other):
        """
        Check if there is an intersection of two arcs
        @param, a second arc which shall be checked for intersection
        @return: True if there is an intersection
        """
        inter = self.find_inter_point_a_a(other)
        return not(inter is None)

    def intersect_a_p(self, other):
        """
        Check if there is an intersection of an point and a arc
        @param, a second arc which shall be checked for intersection
        @return: True if there is an intersection
        """
        # No intersection possible if point is not within radius
        if not(abs(self.O.distance(other) - self.r) < eps):
            return False
        elif self.PointAng_withinArc(other):
            return True
        else:
            return False

    def match_Ps_to_Pe(self, otherPe):
        """
        This functions adapts the geometry in the way so that the
        startpoint exactly matches the given point
        @param otherPe: This is the end point of the other geometry to
        match with
        """

        self.Ps = otherPe

        # Get the Circle center point with known Start and End Points
        self.O.x = self.Ps.x - self.r * cos(self.s_ang)
        self.O.y = self.Ps.y - self.r * sin(self.s_ang)

        self.length = self.r * abs(self.ext)

        self.calc_bounding_box()
        self.abs_geo = None

    def match_Pe_to_Ps(self, otherPs):
        """
        This functions adapts the geometry in the way so that the
        endpoint exactly matches the given point
        @param otherPs: This is the start point of the other geometry to
        match with
        """

        self.Pe = otherPs

        # Get the Circle center point with known Start and End Points
        self.O.x = self.Pe.x - self.r * cos(self.e_ang)
        self.O.y = self.Pe.y - self.r * sin(self.e_ang)

        self.length = self.r * abs(self.ext)

        self.calc_bounding_box()
        self.abs_geo = None

    def split_into_2geos(self, ipoint=Point()):
        """
        Splits the given geometry into 2 geometries. The
        geometry will be splitted at ipoint.
        @param ipoint: The Point where the intersection occures
        @return: A list of 2 ArcGeo's will be returned.
        """

        # Generate the 2 geometries and their bounding boxes.
        Arc1 = OffArcGeo(Ps=self.Ps, Pe=ipoint, r=self.r,
                         O=self.O, direction=self.ext)

        Arc2 = OffArcGeo(Ps=ipoint, Pe=self.Pe, r=self.r,
                         O=self.O, direction=self.ext)
        return [Arc1, Arc2]

    def trim(self, Point, dir=1, rev_norm=False):
        """
        This instance is used to trim the geometry at the given point. The
        point can be a point on the offset geometry a perpendicular point on
        line will be used for trimming.
        @param Point: The point / perpendicular point for new Geometry
        @param dir: The direction in which the geometry will be kept (1  means
        the beginn will be trimmed)
        @param rev_norm: If the direction of the point is on the reversed side.
        """

        # logger.debug("I'm getting trimmed: %s, %s, %s, %s"
        # % (self, Point, dir, rev_norm))
        newPoint = self.O.get_arc_point(self.O.norm_angle(Point), r=self.r)
        
        new_normal = self.O.unit_vector(newPoint, r=1)
        
        if self.ext < 0:
            new_normal = new_normal * -1
        
#         new_normal = newPoint.unit_vector(self.O, r=1)
#         
#         if self.ext<0:
#             new_normal = new_normal*-1

        # logger.debug(newPoint)
        [Arc1, Arc2] = self.split_into_2geos(newPoint)

        if dir == -1:
            new_arc = Arc1
            if hasattr(self, "end_normal"):
                # new_arc.end_normal = self.end_normal
                # new_arc.start_normal = new_normal

                new_arc.end_normal = new_normal
                new_arc.start_normal = self.start_normal
            # logger.debug(new_arc)
            return new_arc
        else:
            new_arc = Arc2
            if hasattr(self, "end_normal"):
                # new_arc.end_normal = new_normal
                # new_arc.start_normal = self.start_normal

                new_arc.end_normal = self.end_normal
                new_arc.start_normal = new_normal
            # logger.debug(new_arc)
            return new_arc


class OffLineGeo(LineGeo):

    """
    Inherited Class for Shapeoffset only. All related offset functions are
    concentrated here in orde to keep base classes as clean as possible.
    """

    def __init__(self, Ps=None, Pe=None, **kwargs):
        """
        Standard Method to initialize the LineGeo.
        @param Ps: The Start Point of the line
        @param Pe: the End Point of the line
        """

        if ("geo" in kwargs) and ("parent" in kwargs):
            geo = kwargs["geo"]
            parent = kwargs["parent"]

            Ps = geo.Ps.rot_sca_abs(parent=parent)
            Pe = geo.Pe.rot_sca_abs(parent=parent)

        LineGeo.__init__(self, Ps=Ps, Pe=Pe)

    def colinear(self, other):
        """
        Check if two lines with same point self.Pe==other.Ps are colinear. For
        Point it check if the point is colinear with the line self.
        @param other: the possibly colinear line
        """
        if isinstance(other, LineGeo):
            return ((self.Ps.ccw(self.Pe, other.Pe) == 0) and
                    (self.Ps.ccw(self.Pe, other.Ps) == 0))
        elif isinstance(other, Point):
            """
            Return true iff a, b, and c all lie on the same line."
            """
            return self.Ps.ccw(self.Pe, other) == 0
        else:
            logger.debug("Unsupported instance: %s" % type(other))

    def colinearoverlapping(self, other):
        """
        Check if the lines are colinear overlapping
        Ensure A<B, C<D, and A<=C (which you can do by simple swapping). Then:
        •if B<C, the segments are disjoint
        •if B=C, then the intersection is the single point B=C
        •if B>C, then the intersection is the segment [C, min(B, D)]
        @param other: The other line
        @return: True if they are overlapping
        """
        if not(self.colinear(other)):
            return False
        else:
            if self.Ps < self.Pe:
                A = self.Ps
                B = self.Pe
            else:
                A = self.Pe
                B = self.Ps
            if other.Ps < self.Pe:
                C = other.Ps
                D = other.Pe
            else:
                C = other.Pe
                D = other.Ps

            # Swap lines if required
            if not(A <= C):
                A, B, C, D = C, D, A, B

        if B < C:
            return False
        elif B == C:
            return False
        else:
            return True

    def colinearconnected(self, other):
        """
        Check if Lines are connected and colinear
        @param other: Another Line which will be checked
        """

        if not(self.colinear(other)):
            return False
        elif self.Ps == other.Ps:
            return True
        elif self.Pe == other.Ps:
            return True
        elif self.Ps == other.Pe:
            return True
        elif self.Pe == other.Pe:
            return True
        else:
            return False

    def distance(self, other=[]):
        """
        Find the distance between 2 geometry elements. Possible is CCLineGeo
        and ArcGeo
        @param other: the instance of the 2nd geometry element.
        @return: The distance between the two geometries
        """
        if isinstance(other, LineGeo):
            return self.distance_l_l(other)
        elif isinstance(other, Point):
            return self.distance_l_p(other)
        elif isinstance(other, ArcGeo):
            return self.distance_l_a(other)
        else:
            logger.error(
                self.tr("Unsupported geometry type: %s" % type(other)))

    def distance_l_l(self, other):
        """
        Find the distance between 2 ccLineGeo elements.
        @param other: the instance of the 2nd geometry element.
        @return: The distance between the two geometries
        """

        if self.intersect(other):
            return 0.0

        return min(self.distance_l_p(other.Ps),
                   self.distance_l_p(other.Pe),
                   other.distance_l_p(self.Ps),
                   other.distance_l_p(self.Pe))

    def distance_l_a(self, other):
        """
        Find the distance between 2 ccLineGeo elements.
        @param other: the instance of the 2nd geometry element.
        @return: The distance between the two geometries
        """

        if self.intersect(other):
            return 0.0

        # Get the nearest Point to the Center of the Arc
        POnearest = self.get_nearest_point_l_p(other.O)

        # The Line is outside of the Arc
        if other.O.distance(POnearest) > other.r:
            # If the Nearest Point is on Arc Segement it is the neares one.
            # logger.debug("Nearest Point is outside of arc")
            if other.PointAng_withinArc(POnearest):
                return POnearest.distance(other.O.get_arc_point(other.O.norm_angle(POnearest),
                                                                r=other.r))
            elif self.distance(other.Ps) < self.distance(other.Pe):
                return self.get_nearest_point(other.Ps).distance(other.Ps)
            else:
                return self.get_nearest_point(other.Pe).distance(other.Pe)

        # logger.debug("Nearest Point is Inside of arc")
        # logger.debug("self.distance(other.Ps): %s, self.distance(other.Pe):
        # %s" %(self.distance(other.Ps),self.distance(other.Pe)))
        # The Line may be inside of the ARc or cross it
        if self.distance(other.Ps) < self.distance(other.Pe):
            dis_min = self.distance(other.Ps)
            # logger.debug("Pnearest: %s, distance: %s" %(Pnearest, dis_min))
        else:
            dis_min = self.distance(other.Pe)
            # logger.debug("Pnearest: %s, distance: %s" %(Pnearest, dis_min))

        if ((other.PointAng_withinArc(self.Ps)) and
                abs(other.r - other.O.distance(self.Ps)) < dis_min):
            dis_min = abs(other.r - other.O.distance(self.Ps))
            # logger.debug("Pnearest: %s, distance: %s" %(Pnearest, dis_min))

        if ((other.PointAng_withinArc(self.Pe)) and
                abs((other.r - other.O.distance(self.Pe))) < dis_min):
            dis_min = abs(other.r - other.O.distance(self.Pe))
            # logger.debug("Pnearest: %s, distance: %s" %(Pnearest, dis_min))

        return dis_min

    def find_inter_point(self, other, typ='TIP'):
        """
        Find the intersection between 2 Geo elements. There can be only one
        intersection between 2 lines. Returns also FIP which lay on the ray.
        @param other: the instance of the 2nd geometry element.
        @param typ: Can be "TIP" for True Intersection Point or "Ray" for
        Intersection which is in Ray (of Line)
        @return: a list of intersection points.
        """
        if isinstance(other, LineGeo):
            inter = self.find_inter_point_l_l(other, typ)
            return inter
        elif isinstance(other, ArcGeo):
            inter = self.find_inter_point_l_a(other, typ)
            return inter
        else:
            logger.error("Unsupported Instance: %s" % other.type)

    def find_inter_point_l_l(self, other, typ="TIP"):
        """
        Find the intersection between 2 LineGeo elements. There can be only one
        intersection between 2 lines. Returns also FIP which lay on the ray.
        @param other: the instance of the 2nd geometry element.
        @param typ: Can be "TIP" for True Intersection Point or "Ray" for
        Intersection which is in Ray (of Line)
        @return: a list of intersection points.
        """

        if self.colinear(other):
            return None
        elif typ == 'TIP' and not(self.intersect(other)):
            return None
        elif typ == "TIP" and self.Ps.distance(other.Pe) < eps * 5:
            return other.Pe
        elif typ == "TIP" and self.Pe.distance(other.Ps) < eps * 5:
            return other.Ps

        dx1 = self.Pe.x - self.Ps.x
        dy1 = self.Pe.y - self.Ps.y

        dx2 = other.Pe.x - other.Ps.x
        dy2 = other.Pe.y - other.Ps.y

        dax = self.Ps.x - other.Ps.x
        day = self.Ps.y - other.Ps.y

        # Return nothing if one of the lines has zero length
        if (dx1 == 0 and dy1 == 0) or (dx2 == 0 and dy2 == 0):
            return None

        # If to avoid division by zero.
        try:
            if(abs(dx2) >= abs(dy2)):
                v1 = (day - dax * dy2 / dx2) / (dx1 * dy2 / dx2 - dy1)
                # v2 = (dax + v1 * dx1) / dx2
            else:
                v1 = (dax - day * dx2 / dy2) / (dy1 * dx2 / dy2 - dx1)
                # v2 = (day + v1 * dy1) / dy2
        except ZeroDivisionError:
            return None

        return Point(x=self.Ps.x + v1 * dx1,
                     y=self.Ps.y + v1 * dy1)

    def find_inter_point_l_a(self, Arc, typ="TIP"):
        """
        Find the intersection between 2 Geo elements. The intersection between
        a Line and a Arc is checked here. This function is also used in the
        Arc Class to check Arc -> Line Intersection (the other way around)
        @param Arc: the instance of the 2nd geometry element.
        @param typ: Can be "TIP" for True Intersection Point or "Ray" for
        Intersection which is in Ray (of Line)
        @return: a list of intersection points.
        """

        if typ == "TIP":
            if self.Ps.distance(Arc.Pe) < eps * 5:
                return Arc.Pe
            elif self.Pe.distance(Arc.Ps) < eps * 5:
                return Arc.Ps

        Ldx = self.Pe.x - self.Ps.x
        Ldy = self.Pe.y - self.Ps.y

        # Mitternachtsformel zum berechnen der Nullpunkte der quadratischen
        # Gleichung
        a = pow(Ldx, 2) + pow(Ldy, 2)
        b = 2 * Ldx * (self.Ps.x - Arc.O.x) + 2 * Ldy * (self.Ps.y - Arc.O.y)
        c = pow(self.Ps.x - Arc.O.x, 2) + \
            pow(self.Ps.y - Arc.O.y, 2) - pow(Arc.r, 2)
        root = pow(b, 2) - 4 * a * c

        # If the value under the sqrt is negative there is no intersection.
        if root < 0 or a == 0.0:
            return None

        v1 = (-b + sqrt(root)) / (2 * a)
        v2 = (-b - sqrt(root)) / (2 * a)

        Pi1 = Point(x=self.Ps.x + v1 * Ldx,
                    y=self.Ps.y + v1 * Ldy)

        Pi2 = Point(x=self.Ps.x + v2 * Ldx,
                    y=self.Ps.y + v2 * Ldy)

        # dif_ang may return 2*pi which we should interpret as zero here!
        Pi1_v = self.mod_clamp (Arc.dif_ang(Arc.Ps, Pi1, Arc.ext), -2*pi, +2*pi) / Arc.ext
        Pi2_v = self.mod_clamp (Arc.dif_ang(Arc.Ps, Pi2, Arc.ext), -2*pi, +2*pi) / Arc.ext

        if typ == 'TIP':
            if ((Pi1_v >= 0.0 and Pi1_v <= 1.0 and self.intersect(Pi1)) and
                    (Pi1_v >= 0.0 and Pi2_v <= 1.0 and self.intersect(Pi2))):
                if (root == 0):
                    return Pi1
                else:
                    return [Pi1, Pi2]
            elif (Pi1_v >= 0.0 and Pi1_v <= 1.0 and self.intersect(Pi1)):
                return Pi1
            elif (Pi1_v >= 0.0 and Pi2_v <= 1.0 and self.intersect(Pi2)):
                return Pi2
            else:
                return None
        elif typ == "Ray":
            # If the root is zero only one solution and the line is a tangent.
            if(root == 0):
                return Pi1

            return [Pi1, Pi2]
        else:
            logger.error("We should not be here")

    @staticmethod
    def mod_clamp(val,min,max):
        if val <= min:
            return val % min
        elif val >= max:
            return val % max
        return val

    def get_nearest_point(self, other):
        """
        Get the nearest point on a line to another line lieing on the line
        @param other: The Line to be nearest to
        @return: The point which is the nearest to other
        """
        if isinstance(other, LineGeo):
            return self.get_nearest_point_l_l(other)
        elif isinstance(other, ArcGeo):
            return self.get_nearest_point_l_a(other)
        elif isinstance(other, Point):
            return self.get_nearest_point_l_p(other)
        else:
            logger.error("Unsupported Instance: %s" % other.type)

    def get_nearest_point_l_l(self, other):
        """
        Get the nearest point on a line to another line lieing on the line
        @param other: The Line to be nearest to
        @return: The point which is the nearest to other
        """
        # logger.debug(self.intersect(other))
        if self.intersect(other):
            return self.find_inter_point_l_l(other)
        min_dis = self.distance(other)
        if min_dis == self.distance_l_p(other.Ps):
            return self.get_nearest_point_l_p(other.Ps)
        elif min_dis == self.distance_l_p(other.Pe):
            return self.get_nearest_point_l_p(other.Pe)
        elif min_dis == other.distance_l_p(self.Ps):
            return self.Ps
        elif min_dis == other.distance_l_p(self.Pe):
            return self.Pe
        else:
            logger.warning("No solution found")

    def get_nearest_point_l_a(self, other, ret="line"):
        """
        Get the nearest point to a line lieing on the line
        @param other: The Point to be nearest to
        @return: The point which is the nearest to other
        """
        if self.intersect(other):
            return self.find_inter_point_l_a(other)

        # Get the nearest Point to the Center of the Arc
        POnearest = self.get_nearest_point_l_p(other.O)

        # The Line is outside of the Arc
        if other.O.distance(POnearest) > other.r:
            # If the Nearest Point is on Arc Segement it is the neares one.
            # logger.debug("Nearest Point is outside of arc")
            if other.PointAng_withinArc(POnearest):
                if ret == "line":
                    return POnearest
                elif ret == "arc":
                    return other.O.get_arc_point(other.O.norm_angle(POnearest),
                                                 r=other.r)
            elif self.distance(other.Ps) < self.distance(other.Pe):
                if ret == "line":
                    return self.get_nearest_point(other.Ps)
                elif ret == "arc":
                    return other.Ps
            else:
                if ret == "line":
                    return self.get_nearest_point(other.Pe)
                elif ret == "art":
                    return other.Pe

        # logger.debug("Nearest Point is Inside of arc")
        # logger.debug("self.distance(other.Ps): %s, self.distance(other.Pe):
        # %s" %(self.distance(other.Ps),self.distance(other.Pe)))
        # The Line may be inside of the ARc or cross it
        if self.distance(other.Ps) < self.distance(other.Pe):
            Pnearest = self.get_nearest_point(other.Ps)
            Pnother = other.Ps
            dis_min = self.distance(other.Ps)
            # logger.debug("Pnearest: %s, distance: %s" %(Pnearest, dis_min))
        else:
            Pnearest = self.get_nearest_point(other.Pe)
            Pnother = other.Pe
            dis_min = self.distance(other.Pe)
            # logger.debug("Pnearest: %s, distance: %s" %(Pnearest, dis_min))

        if ((other.PointAng_withinArc(self.Ps)) and
                abs(other.r - other.O.distance(self.Ps)) < dis_min):

            Pnearest = self.Ps
            Pnother = other.O.get_arc_point(
                other.O.norm_angle(Pnearest), r=other.r)
            dis_min = abs(other.r - other.O.distance(self.Ps))
            # logger.debug("Pnearest: %s, distance: %s" %(Pnearest, dis_min))

        if ((other.PointAng_withinArc(self.Pe)) and
                abs((other.r - other.O.distance(self.Pe))) < dis_min):
            Pnearest = self.Pe
            Pnother = other.O.get_arc_point(
                other.O.norm_angle(Pnearest), r=other.r)

            dis_min = abs(other.r - other.O.distance(self.Pe))
            # logger.debug("Pnearest: %s, distance: %s" %(Pnearest, dis_min))
        if ret == "line":
            return Pnearest
        elif ret == "arc":
            return Pnother

    def get_nearest_point_l_p(self, other):
        """
        Get the nearest point to a point lieing on the line
        @param other: The Point to be nearest to
        @return: The point which is the nearest to other
        """
        if self.intersect(other):
            return other

        PPoint = self.perpedicular_on_line(other)

        if self.intersect(PPoint):
            return PPoint

        if self.Ps.distance(other) < self.Pe.distance(other):
            return self.Ps
        else:
            return self.Pe

    def intersect(self, other):
        """
        Check if there is an intersection of two geometry elements
        @param, a second geometry which shall be checked for intersection
        @return: True if there is an intersection
        """
        # Do a raw check first with BoundingBox
        # logger.debug("self: %s, \nother: %s, \nintersect: %s"
        # %(self,other,self.BB.hasintersection(other.BB)))
        # logger.debug("self.BB: %s \nother.BB: %s")
        # logger.debug(self.BB.hasintersection(other.BB))
        # We need to test Point first cause it has no BB
        if isinstance(other, Point):
            return self.intersect_l_p(other)
        elif not(self.BB.hasintersection(other.BB)):
            return False
        elif isinstance(other, LineGeo):
            return self.intersect_l_l(other)
        elif isinstance(other, ArcGeo):
            return self.intersect_l_a(other)
        else:
            logger.error("Unsupported Instance: %s" % other.type)

    def intersect_l_a(self, other):
        """
        Check if there is an intersection of the two line
        @param, a second line which shall be checked for intersection
        @return: True if there is an intersection
        """
        inter = self.find_inter_point_l_a(other)
        return not(inter is None)

    def intersect_l_l(self, other):
        """
        Check if there is an intersection of the two line
        @param, a second line which shall be checked for intersection
        @return: True if there is an intersection
        """
        A = self.Ps
        B = self.Pe
        C = other.Ps
        D = other.Pe
        return A.ccw(C, D) != B.ccw(C, D) and A.ccw(B, C) != A.ccw(B, D)

    def intersect_l_p(self, Point):
        """
        Check if Point is colinear and within the Line
        @param Point: A Point which will be checked
        @return: True if point Point intersects the line segment from Ps to Pe.
        Refer to http://stackoverflow.com/questions/328107/
        how-can-you-determine-a-point-is-between-two-other-points-on-a-line-segment
        """
        # (or the degenerate case that all 3 points are coincident)
        # logger.debug(self.colinear(Point))
        return (self.colinear(Point)
                and (self.within(self.Ps.x, Point.x, self.Pe.x)
                     if self.Ps.x != self.Pe.x else
                     self.within(self.Ps.y, Point.y, self.Pe.y)))

    def join_colinear_line(self, other):
        """
        Check if the two lines are colinear connected or inside of each other,
        in this case these lines will be joined to one common line, otherwise
        return both lines
        @param other: a second line
        @return: Return one or two lines
        """
        if self.colinearconnected(other):
            return [OffLineGeo(self.Ps, other.Pe)]
        
            """
            FIXME: This is not working as expected, maybe change to a function going 
            for max distance between points. min max is comparing to 0?.
            """
        elif self.colinearoverlapping(other):
            if self.Ps < self.Pe:
                newPs = min(self.Ps, other.Ps, other.Pe)
                newPe = max(self.Pe, other.Ps, other.Pe)
            else:
                newPs = max(self.Ps, other.Ps, other.Pe)
                newPe = min(self.Pe, other.Ps, other.Pe)
            return [OffLineGeo(newPs, newPe)]
        else:
            return [self, other]

    def match_Ps_to_Pe(self, otherPe):
        """
        This functions adapts the geometry in the way so that the
        startpoint exactly matches the given point
        @param otherPe: This is the end point of the other geometry to
        match with
        """

        self.Ps = otherPe

        self.length = self.Ps.distance(self.Pe)
        self.calc_bounding_box()
        self.abs_geo = None

    def match_Pe_to_Ps(self, otherPs):
        """
        This functions adapts the geometry in the way so that the
        endpoint exactly matches the given point
        @param otherPs: This is the start point of the other geometry to
        match with
        """

        self.Pe = otherPs

        self.length = self.Ps.distance(self.Pe)
        self.calc_bounding_box()
        self.abs_geo = None

    def perpedicular_on_line(self, other):
        """
        This function calculates the perpendicular point on a line (or ray of
        line) with the shortest distance to the point given with other
        @param other: The point to be perpendicular to
        @return: A point which is on line and perpendicular to Point other
        @see: http://stackoverflow.com/questions/1811549/
        perpendicular-on-a-line-from-a-given-point
        """
        # first convert line to normalized unit vector
        unit_vector = self.Ps.unit_vector(self.Pe)

        # translate the point and get the dot product
        lam = ((unit_vector.x * (other.x - self.Ps.x))
               + (unit_vector.y * (other.y - self.Ps.y)))
        return Point(x=(unit_vector.x * lam) + self.Ps.x,
                     y=(unit_vector.y * lam) + self.Ps.y)

    def split_into_2geos(self, ipoint=Point()):
        """
        Splits the given geometry into 2 not self intersection geometries. The
        geometry will be splitted between ipoint and Pe.
        @param ipoint: The Point where the intersection occures
        @return: A list of 2 CCLineGeo's will be returned if Point is inside
        """
        # The Point where the geo shall be splitted
        if not(ipoint):
            return [self]
        elif self.intersect(ipoint):
            Li1 = OffLineGeo(Ps=self.Ps, Pe=ipoint)
            Li2 = OffLineGeo(Ps=ipoint, Pe=self.Pe)
            return [Li1, Li2]
        else:
            return [self]

    def trim(self, Point, dir=1, rev_norm=False):
        """
        This instance is used to trim the geometry at the given point. The
        point can be a point on the offset geometry a perpendicular point on
        line will be used for trimming.
        @param Point: The point / perpendicular point for new Geometry
        @param dir: The direction in which the geometry will be kept (1  means
        the being will be trimmed)
        """
        newPoint = self.perpedicular_on_line(Point)
        if dir == 1:
            new_line = OffLineGeo(newPoint, self.Pe)
            new_line.end_normal = self.end_normal
            new_line.start_normal = self.start_normal
            return new_line
        else:
            new_line = OffLineGeo(self.Ps, newPoint)
            new_line.end_normal = self.end_normal
            new_line.start_normal = self.start_normal
            return new_line

    def within(self, p, q, r):
        "Return true iff q is between p and r (inclusive)."
        return p <= q <= r or r <= q <= p


class OffPoint(Point):

    """
    Inherited Class for Shapeoffset only. All related offset functions are
    concentrated here in order to keep base classes as clean as possible.
    """

    def __init__(self, x=0, y=0, **kwargs):

        if ("geo" in kwargs) and ("parent" in kwargs):

            geo = kwargs["geo"]
            parent = kwargs["parent"]

            x = geo.rot_sca_abs(parent=parent).x
            y = geo.rot_sca_abs(parent=parent).y

        self.x = x
        self.y = y


class ConvexPoint(OffPoint):

    """
    Inherited Class of OffPoint required to identify Convex Points in the
    Offset algorithm..
    """

    def __init__(self, x=0, y=0):
        OffPoint.__init__(self, x=x, y=y)

    def __repr__(self):
        return 'ConvexPoint (X=%6.3f, Y=%6.3f)' % (self.x, self.y)
