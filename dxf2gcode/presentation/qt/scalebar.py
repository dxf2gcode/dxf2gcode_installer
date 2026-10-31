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
Scale bar of the 2D canvas.

The scale bar gives the user an idea of the physical size of the imported
DXF geometry. It is drawn as a viewport overlay (see gui/canvas2d.py), so it
is not part of the scene: it can never end up in the contour processing or
in the exported G-Code.

The length is not a fixed pixel value. It is derived from the real view
transformation of the canvas: the number of viewport pixels per drawing unit
is measured with QGraphicsView.mapToScene() (the very same transformation
that is used to draw the geometry), so the bar follows every zoom, pan and
resize automatically.

The unit of the drawing is taken from the global configuration
(g.config.metric), exactly like the rest of the program does: 1 == metric
(millimetres), 0 == imperial (inches).
"""

from __future__ import absolute_import
from __future__ import division

import logging

import dxf2gcode.bootstrap.runtime_state as g

from dxf2gcode.presentation.qt.qt_compat import QtCore
from dxf2gcode.presentation.qt.qt_compat.QtGui import (QColor, QFont, QPainterPath, QPen)


logger = logging.getLogger("Gui.ScaleBar")


# The supported units of measure.
MM = 'mm'
CM = 'cm'
IN = 'in'

# Length of one unit in millimetres.
UNIT_IN_MM = {MM: 1.0, CM: 10.0, IN: 25.4}

# Mantissas of the "nice" lengths (1, 2, 5, 10, 20, 50, 100, ...).
NICE_MANTISSAS = (1.0, 2.0, 5.0)
NICE_EXPONENTS = range(-9, 13)


def drawing_unit(metric=None):
    """
    The unit of the current drawing.
    @param metric: the metric flag of the configuration (g.config.metric).
            1 == metric drawing (millimetres), 0 == imperial drawing (inches).
            A unit name ('mm', 'cm' or 'in') is accepted as well.
            If None, the value of the global configuration is used.
    @return: the unit of the drawing ('mm', 'cm' or 'in')
    """
    if metric is None:
        metric = getattr(getattr(g, 'config', None), 'metric', 1)
    if isinstance(metric, str):
        unit = metric.strip().lower()
        if unit in UNIT_IN_MM:
            return unit
        metric = 1
    return MM if metric else IN


def convert_length(value, from_unit, to_unit):
    """
    Convert a length between the supported units.
    @param value: the length in from_unit
    @param from_unit: the unit of value ('mm', 'cm' or 'in')
    @param to_unit: the wanted unit ('mm', 'cm' or 'in')
    @return: the length in to_unit
    """
    return value * UNIT_IN_MM[from_unit] / UNIT_IN_MM[to_unit]


def format_number(value, decimals=3):
    """
    Format a number without unnecessary decimals ('50.000' -> '50').
    @param value: the number to format
    @param decimals: the maximum number of decimals
    @return: the formatted number
    """
    text = '%.*f' % (decimals, value)
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return text if text else '0'


def format_length(value, unit):
    """
    Format a length together with its unit, e.g. '50 mm', '2 cm', '1 in'.
    @param value: the length in the given unit
    @param unit: the unit of the length ('mm', 'cm' or 'in')
    @return: the formatted length
    """
    return '%s %s' % (format_number(value), unit)


def nice_lengths(limit):
    """
    All "nice" lengths (1, 2, 5, 10, 20, 50, 100, 200, 500, ...) that are not
    greater than the given limit.
    @param limit: the biggest accepted length
    @return: a list of nice lengths in ascending order
    """
    lengths = []
    # The tolerance avoids that a length is lost because of a rounding error
    # of the floating point arithmetic (e.g. 0.3 vs. 0.30000000000000004).
    tolerance = limit * (1.0 + 1e-9)
    for exponent in NICE_EXPONENTS:
        for mantissa in NICE_MANTISSAS:
            value = mantissa * 10.0 ** exponent
            if value <= tolerance:
                lengths.append(value)
    return lengths


def select_scale_length(px_per_unit, target_px=100.0, min_px=60.0, max_px=150.0):
    """
    Choose the length of the scale bar for the given zoom level.
    @param px_per_unit: the number of viewport pixels per drawing unit
    @param target_px: the wanted width of the bar in pixels
    @param min_px: the smallest acceptable width of the bar in pixels
    @param max_px: the biggest acceptable width of the bar in pixels
    @return: (length, pixels) the length in drawing units and its width in
            pixels. length is None if no length could be determined.
    """
    if not px_per_unit or px_per_unit <= 0:
        return None, 0.0

    limit = max_px / px_per_unit
    candidates = nice_lengths(limit)
    if not candidates:
        # Not even the smallest nice length fits into the wanted width
        # (extreme zoom in): use the full width instead of an unusable bar.
        return limit, float(max_px)

    # Prefer a candidate whose width is inside the wanted range and as close
    # to the target width as possible.
    best = None
    for length in candidates:
        pixels = length * px_per_unit
        if min_px <= pixels <= max_px:
            if best is None or abs(pixels - target_px) < abs(best[1] - target_px):
                best = (length, pixels)
    if best is not None:
        return best

    # No candidate fits into the range: use the biggest one that is not
    # wider than the maximum.
    length = candidates[-1]
    return length, length * px_per_unit


class ScaleBarState(object):
    """
    Keeps the length that is currently displayed by the scale bar.

    A new length is only chosen when the current one does not fit into the
    wanted pixel range anymore. Without this, the label would change back and
    forth between two values while zooming.
    """

    def __init__(self):
        self.length = None
        self.unit = None

    def reset(self):
        """
        Forget the current length (the next update recalculates it).
        """
        self.length = None
        self.unit = None

    def update(self, px_per_unit, unit, target_px=100.0, min_px=60.0,
               max_px=150.0):
        """
        Get the length to display.
        @param px_per_unit: the number of viewport pixels per drawing unit
        @param unit: the unit of the drawing
        @return: (length, pixels) the length in drawing units and its width
                in pixels
        """
        if self.unit != unit:
            # The unit changed, the old length has no meaning anymore.
            self.length = None
            self.unit = unit

        length, pixels = select_scale_length(px_per_unit, target_px,
                                              min_px, max_px)

        if self.length is not None and px_per_unit:
            current_pixels = self.length * px_per_unit
            if min_px <= current_pixels <= max_px:
                # The current length is still readable: keep it.
                return self.length, current_pixels

        self.length = length
        return length, pixels


class ScaleBar(object):
    """
    The scale bar overlay of the canvas.

    All the drawing is done in viewport coordinates, so the bar always stays
    at the same place in the visible area, no matter how the geometry is
    panned, zoomed or how the window is resized.
    """

    # Distance to the right and to the bottom border of the viewport (pixels)
    MARGIN = 12
    # Height of the end marks of the bar (pixels)
    TICK_HEIGHT = 6
    # Distance between the bar and its label (pixels)
    LABEL_GAP = 3
    # Size of the label font (pixels)
    FONT_PIXEL_SIZE = 11

    def __init__(self, state=None, target_px=100.0, min_px=60.0,
                 max_px=150.0):
        """
        @param state: the ScaleBarState to keep the displayed length
        @param target_px: the wanted width of the bar in pixels
        @param min_px: the smallest acceptable width of the bar in pixels
        @param max_px: the biggest acceptable width of the bar in pixels
        """
        self.state = state if state is not None else ScaleBarState()
        self.target_px = target_px
        self.min_px = min_px
        self.max_px = max_px

        self.font = QFont()
        self.font.setPixelSize(self.FONT_PIXEL_SIZE)

        self.pen = QPen(QColor(0, 0, 0), 1, QtCore.Qt.PenStyle.SolidLine)
        self.frame_pen = QPen(QColor(120, 120, 120), 1,
                              QtCore.Qt.PenStyle.SolidLine)
        self.frame_brush = QColor(255, 255, 255, 220)

        self.length = None    # the displayed length in drawing units
        self.pixels = 0.0     # the width of the bar in viewport pixels
        self.label = ''       # the text of the label

        self._label_path = None
        self._label_path_text = None

    def update(self, px_per_unit, unit):
        """
        Recalculate the length and the label of the scale bar.
        @param px_per_unit: the number of viewport pixels per drawing unit
        @param unit: the unit of the drawing
        @return: (length, pixels) the length in drawing units and its width
                in pixels
        """
        length, pixels = self.state.update(px_per_unit, unit,
                                           self.target_px, self.min_px,
                                           self.max_px)
        self.length = length
        self.pixels = pixels
        self.label = format_length(length, unit) if length is not None else ''
        return length, pixels

    def text_size(self):
        """
        The size of the label text.
        @return: (width, height) in pixels
        """
        rect = self.label_path().boundingRect()
        return rect.width(), rect.height()

    def label_path(self):
        """
        The label as a painter path.
        The text is converted into a path (the same way the route text of the
        canvas does it, see gui/routetext.py). A path is drawn by the canvas
        painter like any other geometry, so the label stays readable
        independently of the font handling of the painter.
        @return: the path of the label (QPainterPath)
        """
        if self._label_path is None or self._label_path_text != self.label:
            path = QPainterPath()
            if self.label:
                path.addText(QtCore.QPointF(0, 0), self.font, self.label)
            self._label_path = path
            self._label_path_text = self.label
        return self._label_path

    def layout(self, viewport_rect):
        """
        Compute the position of the scale bar inside the viewport.
        @param viewport_rect: the visible area of the canvas (QRect)
        @return: (bar_rect, text_rect) both QRectF in viewport coordinates
        """
        text_width, text_height = self.text_size()

        right = viewport_rect.right() - self.MARGIN
        bottom = viewport_rect.bottom() - self.MARGIN

        text_rect = QtCore.QRectF(right - text_width, bottom - text_height,
                                  text_width, text_height)
        bar_bottom = text_rect.top() - self.LABEL_GAP
        bar_top = bar_bottom - self.TICK_HEIGHT
        bar_rect = QtCore.QRectF(right - self.pixels, bar_top, self.pixels,
                                 self.TICK_HEIGHT)
        return bar_rect, text_rect

    def paint(self, painter, viewport_rect):
        """
        Draw the scale bar.
        The bar is drawn in viewport coordinates (the caller compensates the
        zoom of the canvas), so it always stays at the same place in the
        visible area.
        @param painter: the painter of the canvas
        @param viewport_rect: the visible area of the canvas (QRect)
        """
        if self.length is None or not self.label:
            return

        bar_rect, text_rect = self.layout(viewport_rect)

        # A frame around the whole scale bar keeps it readable, even if it
        # is drawn on top of the geometry.
        frame_rect = bar_rect.united(text_rect).adjusted(-3, -3, 3, 3)

        painter.save()
        try:
            painter.setPen(self.frame_pen)
            painter.setBrush(self.frame_brush)
            painter.drawRect(frame_rect)

            painter.setPen(self.pen)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)

            # The bar itself and its end marks
            middle = bar_rect.center().y()
            painter.drawLine(QtCore.QPointF(bar_rect.left(), middle),
                             QtCore.QPointF(bar_rect.right(), middle))
            painter.drawLine(QtCore.QPointF(bar_rect.left(), bar_rect.top()),
                             QtCore.QPointF(bar_rect.left(), bar_rect.bottom()))
            painter.drawLine(QtCore.QPointF(bar_rect.right(), bar_rect.top()),
                             QtCore.QPointF(bar_rect.right(), bar_rect.bottom()))

            label = self.label_path()
            if not label.isEmpty():
                # The path of the text starts at its baseline: move it to the
                # wanted position before filling it.
                bounds = label.boundingRect()
                painter.save()
                try:
                    painter.translate(text_rect.left() - bounds.left(),
                                      text_rect.bottom() - bounds.bottom())
                    painter.fillPath(label, self.pen.color())
                finally:
                    painter.restore()
        finally:
            painter.restore()


def scale_bar_enabled(config=None):
    """
    Whether the scale bar shall be drawn.
    The state is taken from the configuration option 'show_scale_bar'
    ([General] section), which is disabled by default.
    @param config: the configuration to use, the global one by default
    @return: True if the scale bar shall be drawn
    """
    cfg = config if config is not None else getattr(g, 'config', None)
    if cfg is None:
        return False
    try:
        return bool(cfg.var_dict['General']['show_scale_bar'])
    except (AttributeError, KeyError, TypeError):
        pass
    # Fall back to the readonly structure of the configuration
    try:
        return bool(cfg.vars.General['show_scale_bar'])
    except (AttributeError, KeyError, TypeError):
        return False
