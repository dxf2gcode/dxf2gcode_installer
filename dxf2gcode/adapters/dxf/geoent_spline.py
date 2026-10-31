# -*- coding: utf-8 -*-

############################################################################
#
#   Copyright (C) 2008-2015
#    Christian Kohlöffel
#    Vinzenz Schulz
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

from dxf2gcode.domain.geometry.point import Point
from dxf2gcode.adapters.dxf.spline_convert import Spline2Arcs
from dxf2gcode.adapters.dxf.classes import PointsClass, ContourClass
from dxf2gcode.application.text_helpers import a2u

import dxf2gcode.bootstrap.runtime_state as g


def _chord(geo):
    """
    The distance between the start and the end point of a geometry element.
    @param geo: a LineGeo or ArcGeo
    @return: the chord length
    """
    return geo.get_start_end_points(True).distance(
        geo.get_start_end_points(False))


def _drop_end_element(geos, index, max_chord):
    """
    Drop a negligible end element if its neighbour is much longer.
    @param geos: the geometry list (modified in place)
    @param index: 0 for the first element, -1 for the last element
    @param max_chord: the largest chord which counts as negligible
    @return: True if an element was dropped
    """
    if len(geos) < 2:
        return False
    geo = geos[index]
    neighbour = geos[-2] if index == -1 else geos[1]
    chord = _chord(geo)
    neighbour_chord = _chord(neighbour)
    if chord <= max_chord and neighbour_chord > 10.0 * chord:
        del geos[index]
        return True
    return False


def drop_degenerate_end_geos(geos, cpoints, tol):
    """
    Drop a degenerate end element of an open spline.

    A repeated control point at the end of an open spline creates a zero
    tangent there. The biarc conversion then fits a very small element at
    that end (for the spline 9 of test.dxf: r=0.106863 mm and a chord of
    0.007369 mm). That element is not a feature of the spline; it makes the
    cutter compensation collapse because its radius is smaller than the tool
    radius. It is dropped when

      * the spline is open,
      * the control points at that end are duplicated (within tol),
      * the element is geometrically negligible (chord <= 10 * tol) and
      * the neighbouring element is much longer (> 10 * chord).

    A real short element (without a duplicated end control point) and a
    closed spline are not touched. The end point moves by at most 10 * tol
    (0.01 mm with the default tolerance), which is below the fitting
    tolerance of the drawing.
    @param geos: the converted geometry (modified in place)
    @param cpoints: the control points of the spline
    @param tol: the fitting tolerance of the spline conversion
    """
    if len(geos) < 2 or len(cpoints) < 3:
        return
    if cpoints[0].within_tol(cpoints[-1], tol):
        # A closed spline: its two ends belong together, do not open it.
        return
    max_chord = 10.0 * tol
    if cpoints[-1].within_tol(cpoints[-2], tol):
        _drop_end_element(geos, -1, max_chord)
    if len(geos) >= 2 and cpoints[0].within_tol(cpoints[1], tol):
        _drop_end_element(geos, 0, max_chord)


class GeoentSpline:
    def __init__(self, Nr=0, caller=None):
        self.Typ = 'Spline'
        self.Nr = Nr
        self.config = getattr(caller, "config", None) or g.config

        # Initialisieren der Werte
        # Initialise the values
        self.Layer_Nr = 0
        self.Spline_flag = []
        self.degree = 1
        self.Knots = []
        self.Weights = []
        self.CPoints = []
        self.geo = []
        self.length = 0.0

        # Lesen der Geometrie
        # Read the geometry
        self.Read(caller)

        # Zuweisen der Toleranz f�rs Fitting
        # Assign the fitting tolerance
        tol = self.config.fitting_tolerance
        check = self.config.vars.Import_Parameters['spline_check']

        # Umwandeln zu einem ArcSpline
        # Convert to a ArcSpline
        Spline2ArcsClass = Spline2Arcs(degree=self.degree, Knots=self.Knots,
                                       Weights=self.Weights, CPoints=self.CPoints, tol=tol, check=check)

        self.geo = Spline2ArcsClass.Curve

        # A repeated control point at the end of an open spline makes the
        # biarc conversion generate a degenerate micro element there. Drop it
        # before the geometry is used (see drop_degenerate_end_geos).
        drop_degenerate_end_geos(self.geo, self.CPoints, tol)

        for geo in self.geo:
            self.length += geo.length

    def __repr__(self):
        # how to print the object
        s = "\nSpline:" +\
            "\n\tNr: %i" % self.Nr +\
            "\n\tLayer Nr: %i" % self.Layer_Nr +\
            "\n\tSpline flag: %i" % self.Spline_flag +\
            "\n\tdegree: %i" % self.degree +\
            "\n\tlength: %0.3f" % self.length +\
            "\n\tGeo elements: %i" % len(self.geo) +\
            "\n\tKnots: %s" % self.Knots +\
            "\n\tWeights: %s" % self.Weights +\
            "\n\tCPoints:"

        for Point in self.CPoints:
            s = s + str(Point)

        return s

    def reverse(self):
        """
        reverse()
        """
        self.geo.reverse()
        for geo in self.geo:
            geo.reverse()

    def App_Cont_or_Calc_IntPts(self, cont, points, i, tol):
        """
        App_Cont_or_Calc_IntPts()
        """
        # Hinzuf�gen falls es keine geschlossener Spline ist
        # Add if it is not a closed spline
        if self.CPoints[0].within_tol(self.CPoints[-1], tol):
            self.analyse_and_opt()
            cont.append(ContourClass(len(cont), 1, [[i, 0]], self.length))
        else:
            points.append(PointsClass(point_nr=len(points), geo_nr=i,
                                      Layer_Nr=self.Layer_Nr,
                                      be=self.geo[0].Ps,
                                      en=self.geo[-1].Pe,
                                      be_cp=[], en_cp=[]))
        return True

    def analyse_and_opt(self):
        """
        analyse_and_opt()
        """
        summe = 0

        # Richtung in welcher der Anfang liegen soll (unten links)
        # Direction of the top (lower left) ???
        Popt = Point(-1e3, -1e6)

        # Calculation of the alignment after Gaussian-Elling
        # Positive value means CW, negative value indicates CCW
        # closed polygon
        for Line in self.geo:
            summe += Line.Ps.x * Line.Pe.y - Line.Pe.x * Line.Ps.y

        if summe > 0.0:
            self.reverse()

        # Find the smallest starting point from bottom left X (Must be new loop!)
        # logger.debug(self.geo)

        min_distance = self.geo[0].Ps.distance(Popt)
        min_geo_nr = 0
        for geo_nr in range(1, len(self.geo)):
            if self.geo[geo_nr].Ps.distance(Popt) < min_distance:
                min_distance = self.geo[geo_nr].Ps.distance(Popt)
                min_geo_nr = geo_nr

        # Order contour so the new starting point is at the beginning
        self.geo = self.geo[min_geo_nr:len(self.geo)] + self.geo[0:min_geo_nr]

    def Read(self, caller):
        """
        Read()
        """
        # Assign short name
        lp = caller.line_pairs
        e = lp.index_code(0, caller.start + 1)

        # Assign layer
        s = lp.index_code(8, caller.start + 1)
        self.Layer_Nr = caller.Get_Layer_Nr(a2u(lp.line_pair[s].value))

        # Spline Flap zuweisen
        # Assign Spline Flap
        s = lp.index_code(70, s + 1)
        self.Spline_flag = int(lp.line_pair[s].value)

        # Spline Ordnung zuweisen
        # Spline order to assign
        s = lp.index_code(71, s + 1)
        self.degree = int(lp.line_pair[s].value)

        # Number of CPts
        st = lp.index_code(73, s + 1)
        nCPts = int(lp.line_pair[s].value)

        s = st
        # Read the node (knot)
        while True:
            # N ode (knot) value
            sk = lp.index_code(40, s + 1, e)
            if sk is None:
                break
            self.Knots.append(float(lp.line_pair[sk].value))
            s = sk

        # Read the weights
        s = st
        while True:
            # Node (knot) weights
            sg = lp.index_code(41, s + 1, e)
            if sg is None:
                break
            self.Weights.append(float(lp.line_pair[sg].value))
            s = sg

        # Read the control points
        s = st
        while True:
            # X value
            s = lp.index_code(10, s + 1, e)
            # Wenn kein neuer Punkt mehr gefunden wurde abbrechen ...
            # Cancel if no new item was detected
            if s is None:
                break
            x = float(lp.line_pair[s].value)

            # Y value
            s = lp.index_code(20, s + 1, e)
            y = float(lp.line_pair[s].value)

            self.CPoints.append(Point(x, y))

        if len(self.Weights) == 0:
            for nr in range(len(self.CPoints)):
                self.Weights.append(1)

        caller.start = e

    #        print nCPts
    #        print len(self.Knots)
    #        print len(self.Weights)
    #        print len(self.CPoints)
    #        print self

    def get_start_end_points(self, direction=0):
        """
        get_start_end_points()
        """
        if not direction:
            punkt, angle = self.geo[0].get_start_end_points(direction)
        else:
            punkt, angle = self.geo[-1].get_start_end_points(direction)

        return punkt, angle
