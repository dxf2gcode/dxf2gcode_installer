# -*- coding: utf-8 -*-

############################################################################
#
#   Copyright (C) 2011-2015
#    Christian Kohlöffel
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

import logging

import dxf2gcode.bootstrap.runtime_state as g
#TODO: check if can be removed:
#from dxf2gcode.domain.geometry.linegeo import LineGeo
#from dxf2gcode.domain.geometry.point import Point
from dxf2gcode.domain.geometry.arcgeo import ArcGeo
#from dxf2gcode.domain.geometry.holegeo import HoleGeo

import dxf2gcode.domain.constants as c
from dxf2gcode.presentation.qt.qt_compat.QtWidgets import QGraphicsView, QMenu
from dxf2gcode.presentation.qt.qt_compat import QtCore
from dxf2gcode.presentation.qt.qt_compat.QtGui import QMouseEvent, QKeyEvent, QIcon, QPixmap, QPainter, QPen
from dxf2gcode.presentation.qt.qt_compat.QtWidgets import QApplication
from dxf2gcode.presentation.qt.qt_compat.QtCore import Qt


logger = logging.getLogger("Gui.Canvas")

_MIXED_SELECTION_ICON = None


def mixedSelectionIcon():
    """
    A small "partially checked" icon (a boxed minus), drawn programmatically so
    no resource file is needed. It is shown to the left of a context menu entry
    to indicate a mixed selection state (QAction has no native
    Qt.PartiallyChecked display).
    """
    global _MIXED_SELECTION_ICON
    if _MIXED_SELECTION_ICON is None:
        size = 14
        pixmap = QPixmap(size, size)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        pen = QPen(QtCore.Qt.GlobalColor.black)
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawRect(1, 1, size - 3, size - 3)              # box frame
        painter.drawLine(4, size // 2, size - 5, size // 2)     # "minus"
        painter.end()
        _MIXED_SELECTION_ICON = QIcon(pixmap)
    return _MIXED_SELECTION_ICON


"""
This Canvas function can be called as any class.
Since it will pretend to be, depending on the settings,
to be the canvas3d or canvas2d class
"""
def Canvas(parent=None):
    if g.config.mode3d:
        from dxf2gcode.presentation.qt.canvas3d import GLWidget
        return GLWidget(parent)
    else:
        from dxf2gcode.presentation.qt.canvas2d import MyGraphicsView
        return MyGraphicsView(parent)

def CanvasObject():
    if g.config.mode3d:
        QtVersion = QtCore.QT_VERSION_STR.split(".")
        if not (int(QtVersion[0]) >= 5 and int(QtVersion[1]) >= 4):
            raise Exception("For the 3d mode you need a PyQt version that includes a Qt version of at least 5.4.\n"
                            "Set mode3d to False in the config file, or update your PyQt version.\n"
                            "Current version found: PyQt%s (which includes Qt%s)"
                            % (QtCore.PYQT_VERSION_STR, QtCore.QT_VERSION_STR))
        from dxf2gcode.presentation.qt.qt_compat.QtOpenGLWidgets import QOpenGLWidget
        return QOpenGLWidget
    else:
        return QGraphicsView

class CanvasBase(CanvasObject()):
    def __init__(self, parent=None):
        super(CanvasBase, self).__init__(parent)

        self.isPanning = False
        self.isRotating = False
        self.isMultiSelect = False

        self.setMouseTracking (True)


    def updateModifiers(self, event):
        """
        Handle all canvas keyboard modifiers in one place.
        """

        if type (event) == QMouseEvent:
            buttons = event.buttons()
        else:
            buttons = QApplication.mouseButtons()

        if type (event) == QKeyEvent:
            modifiers = event.modifiers()
        else:
            modifiers = QApplication.keyboardModifiers()

        # allow only clean modifiers, no combos
        wantMultiSelect = (modifiers == Qt.KeyboardModifier.ControlModifier)
        self.isMultiSelect = wantMultiSelect and ((buttons == Qt.MouseButton.NoButton) or (buttons == Qt.MouseButton.LeftButton))
        wantPanning = (modifiers == Qt.KeyboardModifier.ShiftModifier)
        self.isPanning = wantPanning and (buttons == Qt.MouseButton.LeftButton)
        wantRotating = (modifiers == Qt.KeyboardModifier.AltModifier)
        self.isRotating = wantRotating and (buttons == Qt.MouseButton.LeftButton)

        if self.isPanning or self.isRotating:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif wantPanning:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif wantRotating:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif wantMultiSelect:
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.unsetCursor()


class MyDropDownMenu(QMenu):
    def __init__(self, canvas_scene, position, clicked, offset=None):
        QMenu.__init__(self)

        self.clicked = clicked
        self.offset = offset

        self.canvas_scene = canvas_scene

        self.selectedItems = [shape for shape in canvas_scene.shapes if shape.isSelected()]

        if len(self.selectedItems) == 0:
            return

        invertAction = self.addAction(self.tr("Invert Selection"))
        disableAction = self.addAction(self.tr("Disable Selection"))
        enableAction = self.addAction(self.tr("Enable Selection"))

        self.addSeparator()

        swdirectionAction = self.addAction(self.tr("Switch Direction"))
        SetNxtStPAction = self.addAction(self.tr("Set Nearest StartPoint"))
        setSharStAction = self.addAction(self.tr("Set Sharpest StartPoint"))

        self.addSeparator()
        
        #enable pocket mill only if all selected shapes are closed
        allClosed = True
        allArcs = True
        
        for item in self.selectedItems:
            if item.closed == False:
                allClosed == False
                break
            for geo in item.geos:
                if not(isinstance(geo, ArcGeo)):
                    allArcs = False
                    
        
            
        #if all are closed and compensation is NOT done by machine,
        # since I do not know how this should work... /SZ
        # The drag knife does not support the pocket milling: the entry is
        # not shown at all in the context menu.
        if (g.config.machine_type != 'drag_knife' and
                allClosed == True and
                not g.config.vars.Cutter_Compensation["done_by_machine"]):
            self.PocketAction = self.addAction(self.tr("Pocket Mill"))
            self.PocketAction.setCheckable(True)
            self.PocketAction.triggered.connect(self.setPocket)
            self._updateBoolActionState(self.PocketAction, "Pocket")

        #ONly allow it it's a closed shaep
        if (allClosed == True) and (allArcs == True):
            self.DrillAction = self.addAction(self.tr("Drill Bore"))
            self.DrillAction.setCheckable(True)
            #HoleAction.triggered.connect(self.setHoleGeo)
            self.DrillAction.triggered.connect(self.setDrill)
            self._updateBoolActionState(self.DrillAction, "Drill")
            

        if g.config.machine_type == 'drag_knife':
            pass
        else:
            self.addSeparator()
            submenu1 = QMenu(self.tr('Cutter Compensation'), self)
            self.noCompAction = submenu1.addAction(self.tr("G40 No Compensation"))
            self.noCompAction.setCheckable(True)
            self.leCompAction = submenu1.addAction(self.tr("G41 Left Compensation"))
            self.leCompAction.setCheckable(True)
            self.reCompAction = submenu1.addAction(self.tr("G42 Right Compensation"))
            self.reCompAction.setCheckable(True)

            self.compMenuAction = submenu1.menuAction()
            logger.debug(self.tr("The selected shapes have the following direction: %i") % (self.calcMenuDir()))
            self.checkMenuDir(self.calcMenuDir())

            self.addMenu(submenu1)

        invertAction.triggered.connect(self.invertSelection)
        disableAction.triggered.connect(self.disableSelection)
        enableAction.triggered.connect(self.enableSelection)

        swdirectionAction.triggered.connect(self.switchDirection)
        SetNxtStPAction.triggered.connect(self.setNearestStPoint)
        setSharStAction.triggered.connect(self.setSharpestStPoint)



        if g.config.machine_type == 'drag_knife':
            pass
        else:
            self.noCompAction.triggered.connect(self.setNoComp)
            self.leCompAction.triggered.connect(self.setLeftComp)
            self.reCompAction.triggered.connect(self.setRightComp)

        self.exec(position)

    def tr(self, string_to_translate):
        """
        Translate a string using the QCoreApplication translation framework
        @param string_to_translate: a unicode string
        @return: the translated unicode string if it was possible to translate
        """
        return str(QtCore.QCoreApplication.translate('MyDropDownMenu',
                                                           string_to_translate))

    def calcMenuDir(self):
        """
        This method returns the direction of the selected items. If there are
        different cutter directions in the selection 0 is returned, else
        1 for Left and 2 for right.
        """
        dir = self.selectedItems[0].cut_cor
        for item in self.selectedItems:
            if not(dir == item.cut_cor):
                return -1

        return dir-40

    def checkMenuDir(self, dir):
        """
        This method checks the buttons in the Contextmenu for the direction of
        the selected items.
        @param dir: The direction of the items -1=different, 0=None, 1=left, 2=right
        """
        self.noCompAction.setChecked(False)
        self.leCompAction.setChecked(False)
        self.reCompAction.setChecked(False)

        if dir == 0:
            self.noCompAction.setChecked(True)
        elif dir == 1:
            self.leCompAction.setChecked(True)
        elif dir == 2:
            self.reCompAction.setChecked(True)

        # Mixed cutter compensation (dir == -1): no option is checked; show the
        # "mixed" icon on the submenu action instead (its text stays unchanged).
        comp_action = getattr(self, "compMenuAction", None)
        if comp_action is not None:
            comp_action.blockSignals(True)
            try:
                if dir == -1:
                    comp_action.setIcon(mixedSelectionIcon())
                else:
                    comp_action.setIcon(QIcon())
            finally:
                comp_action.blockSignals(False)

    def _selectionBoolState(self, attr):
        """
        Aggregate the boolean attribute 'attr' over the selected shapes.
        @return: "on" if all are True, "off" if all are False, "mixed" otherwise
        """
        values = [bool(getattr(shape, attr)) for shape in self.selectedItems]
        if all(values):
            return "on"
        if not any(values):
            return "off"
        return "mixed"

    def _updateBoolActionState(self, action, attr):
        """
        Update a checkable action to reflect the aggregated state of the
        selection: checked when all shapes have the attribute set, unchecked
        when none has it, and a dedicated "mixed" icon (drawn without a check
        mark) when the selection is mixed. The action text is never touched.
        @param action: the checkable QAction
        @param attr: the boolean attribute name on the shapes
        """
        state = self._selectionBoolState(attr)
        action.blockSignals(True)  # never fire triggered/toggled here
        try:
            if state == "mixed":
                action.setChecked(False)
                action.setIcon(mixedSelectionIcon())
            else:
                action.setChecked(state == "on")
                action.setIcon(QIcon())
        finally:
            action.blockSignals(False)

    def invertSelection(self):
        """
        This function is called by the Contextmenu of the Graphicsview.
        @purpose: Inverts the selection of all shapes.
        """
        for shape in self.canvas_scene.shapes:
            self.canvas_scene.set_shape_selected(
                shape, not shape.isSelected())
            g.window.TreeHandler.updateShapeSelection(shape, shape.isSelected())
        self.canvas_scene.update()

    def disableSelection(self):
        """
        Disable all shapes which are currently selected. Based on the view
        options they are not shown, or showed in a different color
        """
        for shape in self.selectedItems:
            if shape.allowedToChange:
                self.canvas_scene.set_shape_disabled(shape, True)
                g.window.TreeHandler.updateShapeEnabling(shape, False)
        self.canvas_scene.update()

    def enableSelection(self):
        """
        Enable all shapes which are currently selected. Based on the view
        options they are not shown, or showed in a different color
        """
        for shape in self.selectedItems:
            if shape.allowedToChange:
                self.canvas_scene.set_shape_disabled(shape, False)
                g.window.TreeHandler.updateShapeEnabling(shape, True)
        self.canvas_scene.update()

    def switchDirection(self):
        """
        Switch the Direction of all items. For example from CW direction to CCW
        """
        for shape in self.selectedItems:
            shape.reverse()
            logger.debug(self.tr('Switched Direction at Shape Nr: %i') % shape.nr)
            self.canvas_scene.repaint_shape(shape)
        self.canvas_scene.update()
        g.window.TreeHandler.prepareExportOrderUpdate()

    def setNearestStPoint(self):
        """
        Search the nearest StartPoint to the clicked position of all selected shapes.
        """
        xyForZ = {}
        for shape in self.selectedItems:
            clicked = self.clicked
            if self.offset is not None:
                z = shape.axis3_start_mill_depth
                if z not in xyForZ:
                    clicked = xyForZ[z] = self.canvas_scene.determineSelectedPosition(self.clicked, z, self.offset)
            shape.setNearestStPoint(clicked)
            self.canvas_scene.repaint_shape(shape)
        g.window.updateExportRoute()

    def setSharpestStPoint(self):
        """
        Search the sharpest StartPoint of all selected shapes.
        """
        for shape in self.selectedItems:
            shape.setSharpestStPoint()
            self.canvas_scene.repaint_shape(shape)
        g.window.updateExportRoute()

    def setNoComp(self):
        """
        Sets the compensation to 40, which is none, for the selected shapes.
        """
        for shape in self.selectedItems:
            shape.cut_cor = 40
            logger.debug(self.tr('Changed Cutter Correction to None for shape: %i') % shape.nr)
            self.canvas_scene.repaint_shape(shape)
        self.canvas_scene.update()

    def setLeftComp(self):
        """
        Sets the compensation to 41, which is Left, for the selected shapes.
        """
        for shape in self.selectedItems:
            shape.cut_cor = 41
            logger.debug(self.tr('Changed Cutter Correction to left for shape: %i') % shape.nr)
            self.canvas_scene.repaint_shape(shape)
        self.canvas_scene.update()

    def setRightComp(self):
        """
        Sets the compensation to 42, which is Right, for the selected shapes.
        """
        for shape in self.selectedItems:
            shape.cut_cor = 42
            logger.debug(self.tr('Changed Cutter Correction to right for shape: %i') % shape.nr)
            self.canvas_scene.repaint_shape(shape)
        self.canvas_scene.update()

    def setPocket(self):
        """
        Enable or disable pocket milling for the selected shapes.

        The new state is applied to ALL selected shapes as ONE uniform group:
        if every selected shape already mills its pocket, the group is turned
        off, otherwise it is turned on. This avoids inverting each shape
        individually (which left a mixed multi-selection inconsistent and
        disabled an already enabled shape).
        """
        if not self.selectedItems:
            return
        target = not all(shape.Pocket for shape in self.selectedItems)
        for shape in self.selectedItems:
            shape.Pocket = target
            logger.debug(self.tr('Set to %s for Pocket Mill for shape: %i')
                         % (target, shape.nr))
            g.window.TreeHandler.updatePocketMill(shape, target)
            self.canvas_scene.repaint_shape(shape)
        self.PocketAction.setChecked(target)
        self.canvas_scene.update()
    
    def setDrill(self):
        """
        Enable or disable G73 drilling for the selected shapes.

        The new state is applied to ALL selected shapes as ONE uniform group
        (all off -> all on, otherwise all off), never by inverting each shape
        individually.
        """
        if not self.selectedItems:
            return
        target = not all(shape.Drill for shape in self.selectedItems)
        for shape in self.selectedItems:
            shape.Drill = target
            logger.debug(self.tr('Set to %s for G73 Drill, for shape: %i')
                         % (target, shape.nr))
            g.window.TreeHandler.updateDrill(shape, target)
            self.canvas_scene.repaint_shape(shape)
        self.DrillAction.setChecked(target)
        self.canvas_scene.update()
