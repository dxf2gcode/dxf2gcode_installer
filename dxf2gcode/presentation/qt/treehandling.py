# -*- coding: utf-8 -*-

############################################################################
#
#   Copyright (C) 2012-2015
#    Xavier Izard
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

"""
This class is intended to deal with the drawing (.dxf) structure.
It has the following functions:
- populate the entities treeView and the layers treeView
- allow selection of shapes from any treeView and show the
  selection on the graphic view
- allow to enable/disable shapes from any treeView
- reflects into the treeView the changes that occurs on the graphic view
- set export order using drag & drop

@purpose: display tree structure of the .dxf file, select,
          enable and set export order of the shapes
"""

from __future__ import absolute_import

from math import degrees
import logging

import dxf2gcode.bootstrap.runtime_state as g
from dxf2gcode.application.shapes import (
    ApplyLayerOvercutDefaults, AssignTool, SetShapeBreakPass, SetShapeLeadMode,
    SetShapeOvercut, UpdateLayerParameters, UpdateShapeParameters)

from dxf2gcode.presentation.qt import shapeparameterstate as sps
from dxf2gcode.domain.project.shape import Shape
from dxf2gcode.domain.project.tool_settings import ToolSettings, effective_tool
from dxf2gcode.domain.project.entitycontent import EntityContent
from dxf2gcode.domain.toolpath.customgcode import CustomGCode
from dxf2gcode.domain.toolpath.leadmove import (LEAD_DEFAULT, LEAD_OFF, LEAD_RADIUS,
                                     LEAD_STARTMOVE, LEAD_STRAIGHT,
                                     OVERCUT_DEFAULT, OVERCUT_OFF, OVERCUT_ON,
                                     lead_mode_labels, mode_needs_length,
                                     mode_needs_radius)
from dxf2gcode.presentation.qt.treeview import MyStandardItemModel

from dxf2gcode.application.text_helpers import toInt, toFloat

import dxf2gcode.domain.constants as c
from dxf2gcode.presentation.qt.qt_compat.QtWidgets import QMenu, QWidget, QAbstractItemView, QTreeView
from dxf2gcode.presentation.qt.qt_compat.QtCore import QItemSelectionModel, QItemSelection
from dxf2gcode.presentation.qt.qt_compat.QtGui import QAction, QStandardItem, QIcon, QPixmap, QStandardItemModel, QPalette
from dxf2gcode.presentation.qt.qt_compat import QtCore
isValid = lambda data: data
toPyObject = lambda data: data


class QVariantShape(QtCore.QVariant):
    """
    Wrapper is needed for PyQt5 since this version does not accept to add a QGraphisItem
     directly to a QStandardItem
    """
    def __init__(self, shapeobj):
        self.shapeobj = shapeobj


logger = logging.getLogger("Gui.TreeHandling")


def update_lead_move_values(layer):
    """
    Update the lead in / lead out / overcut values of a layer with the values
    of the tool of the layer and with the global values of the configuration.

    The values which were set by a layer name (see the layer name
    identifiers) are not overwritten.

    The methods of the lead in and of the lead out are not copied into the
    layer: a layer which uses the configuration default (LEAD_DEFAULT)
    follows the global default value, so that a change of the global default
    is applied to all the layers which do not have their own value.
    The same is true for the overcut: a layer which uses the configuration
    default (OVERCUT_DEFAULT) follows the global default value.

    The length of the overcut is defined per tool (see the tools table): the
    layer uses the value of its tool. The values of the tools table are in the
    unit of the drawing.

    @param layer: the layer content
    @return: True if a value of the layer has changed
    """
    return ApplyLayerOvercutDefaults().execute(layer, g.config)


# defines some arbitrary types for the objects stored into the treeView.
# These types will eg help us to find which kind of data is stored
# in the element received from a click() event
ENTITY_OBJECT = QtCore.Qt.ItemDataRole.UserRole + 1  # For storing refs to the entities elements (entities_list)
LAYER_OBJECT = QtCore.Qt.ItemDataRole.UserRole + 2  # For storing refs to the layers elements (layers_list)
SHAPE_OBJECT = QtCore.Qt.ItemDataRole.UserRole + 3  # For storing refs to the shape elements (entities_list & layers_list)
CUSTOM_GCODE_OBJECT = QtCore.Qt.ItemDataRole.UserRole + 4  # For storing refs to the custom gcode elements (layers_list)

PATH_OPTIMISATION_COL = 3  # Column that corresponds to TSP enable checkbox


def break_geometries_present():
    """
    Returns True when at least one shape of a BREAKS layer exists and is
    enabled, i.e. when the BREAKS function can influence the export.
    """
    layers_list = getattr(getattr(g, "window", None), "layerContents", None)
    if layers_list is None:
        return False
    return any(layer.isBreakLayer() and any(not shape.disabled
                                            for shape in layer.shapes)
               for layer in layers_list)


def next_group_check_state(states):
    """
    Decide the uniform check state for a group toggle.

    @param states: iterable of the current checked states (booleans) of the
                   selected items
    @return: the state to apply to ALL selected items: if every item is
             already checked, uncheck all; otherwise check all. This is
             deterministic for mixed selections (a mixed group is switched
             on instead of inverting each item individually).
    """
    states = list(states)
    if states and all(states):
        return False
    return True


class TreeHandler(QWidget):
    """
    Class to handle both QTreeView :  entitiesTreeView (for blocks, and the tree of blocks) and layersShapesTreeView (for layers and shapes)
    """

    def __init__(self, ui):
        """
        Standard method to initialize the class
        @param ui: the GUI
        """
        QWidget.__init__(self)
        self.ui = ui

        # Used to store previous values in order to enable/disable text
        self.palette = self.ui.zRetractionArealLineEdit.palette()
        self.clearToolsParameters()

        # Layers & Shapes TreeView
        self.layer_item_model = None
        self.layers_list = None
        self.auto_update_export_order = False
        self.ui.layersShapesTreeView.setExportOrderUpdateCallback(self.prepareExportOrderUpdate)
        self.ui.layersShapesTreeView.setSelectionCallback(self.actionOnSelectionChange)  # pass the callback function to the QTreeView
        self.ui.layersShapesTreeView.setKeyPressEventCallback(self.actionOnKeyPress)
        self.ui.layersShapesTreeView.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.ui.layersShapesTreeView.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        self.ui.layersGoUpPushButton.clicked.connect(self.ui.layersShapesTreeView.moveUpCurrentItem)
        self.ui.layersGoDownPushButton.clicked.connect(self.ui.layersShapesTreeView.moveDownCurrentItem)

        # Load the tools from the config file to the tool selection combobox
        for tool in g.config.vars.Tool_Parameters:
            self.ui.toolDiameterComboBox.addItem(tool)

        # A tool is displayed only once a shape or layer is selected.
        self.ui.toolDiameterComboBox.setCurrentIndex(-1)

        # The layer/shape which is currently displayed in the parameters box
        self.display_tool_layer = None
        self.display_tool_shape = None
        # whole selection (used to detect and display mixed parameter values)
        self.display_tool_layers = []
        self.display_tool_shapes = []

        # Don't change this line, the signal _must_ be "activated" (only activates on user action) and _not_ "currentIndexChanged" (activates programmatically and on user action)
        self.ui.toolDiameterComboBox.textActivated[str].connect(self.toolUpdate)

        # The methods of the lead in and of the lead out: they are selected
        # independently for every layer. "Configuration default" uses the
        # method which is configured in the configuration file.
        self._fill_lead_mode_combo(self.ui.leadInComboBox, lead_in=True)
        self._fill_lead_mode_combo(self.ui.leadOutComboBox, lead_in=False)
        self.ui.leadInComboBox.activated.connect(self.leadInUpdate)
        self.ui.leadOutComboBox.activated.connect(self.leadOutUpdate)
        # The overcut: it is a setting of the layer, like the method of the
        # lead in and of the lead out.
        self._fill_overcut_combo(self.ui.overcutComboBox)
        self.ui.overcutComboBox.activated.connect(self.overcutUpdate)

        self.ui.zRetractionArealLineEdit.editingFinished.connect(self.toolParameterzRetractionArealUpdate)
        self.ui.zSafetyMarginLineEdit.editingFinished.connect(self.toolParameterzSafetyMarginUpdate)
        self.ui.zInitialMillDepthLineEdit.editingFinished.connect(self.toolParameterzInitialMillDepthUpdate)
        self.ui.zInfeedDepthLineEdit.editingFinished.connect(self.toolParameterzInfeedDepthUpdate)
        self.ui.zFinalMillDepthLineEdit.editingFinished.connect(self.toolParameterzFinalMillDepthUpdate)
        self.ui.millingOffsetLineEdit.editingFinished.connect(self.toolParameterMillingOffsetUpdate)
        self.ui.breaksPassComboBox.activated.connect(self.breaksPassUpdate)
        self.ui.g1FeedXYLineEdit.editingFinished.connect(self.toolParameterg1FeedXYUpdate)
        self.ui.g1FeedZLineEdit.editingFinished.connect(self.toolParameterg1FeedZUpdate)

        # mill settings frame: tooltips and the central display/refresh of
        # the parameter fields (standard, individual and mixed values)
        self.setupMillParameterTooltips()
        for _widget in self._mill_parameter_widgets():
            if hasattr(_widget, "editingFinished"):
                _widget.editingFinished.connect(self.updateToolParameters)
        
        # Entities TreeView
        self.entity_item_model = None
        self.entities_list = None
        self.ui.entitiesTreeView.setSelectionCallback(self.actionOnSelectionChange)  # pass the callback function to the QTreeView
        self.ui.entitiesTreeView.setKeyPressEventCallback(self.actionOnKeyPress)
        self.ui.entitiesTreeView.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.ui.entitiesTreeView.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        for view, collapse_button, expand_button in (
                (self.ui.layersShapesTreeView,
                 self.ui.layersCollapsePushButton, self.ui.layersExpandPushButton),
                (self.ui.entitiesTreeView,
                 self.ui.blocksCollapsePushButton, self.ui.blocksExpandPushButton)):
            self._connectExpansionButtons(view, collapse_button, expand_button)

        # Build the contextual menu (mouse right click)
        self.context_menu = QMenu(self)
        self.context_menu.addAction(QAction(self.tr("Select all"), self, triggered=self.ui.layersShapesTreeView.selectAll))
        self.context_menu.addAction(QAction(self.tr("Deselect all"), self, triggered=self.ui.layersShapesTreeView.clearSelection))
        self.context_menu.addSeparator()
        self.context_menu.addAction(QAction(self.tr("Enable selection"), self, triggered=self.enableSelectedItems))
        self.context_menu.addAction(QAction(self.tr("Disable selection"), self, triggered=self.disableSelectedItems))
        self.context_menu.addSeparator()
        self.context_menu.addAction(QAction(self.tr("Optimize route for selection"), self, triggered=self.optimizeRouteForSelectedItems))
        self.context_menu.addAction(QAction(self.tr("Don't optimize route for selection"), self, triggered=self.doNotOptimizeRouteForSelectedItems))
        self.context_menu.addSeparator()
        self.context_menu.addAction(QAction(self.tr("Remove custom GCode"), self, triggered=self.removeCustomGCodeSelected))

        self.sub_menu = QMenu(self.tr("Add custom GCode ..."), self)
        # Save the exact name of the action, as is defined in the config file. Later on we use it to identify the action
        for custom_action in g.config.vars.Custom_Actions:
            menu_action = self.sub_menu.addAction(custom_action.replace('_', ' '))
            menu_action.setData(custom_action)

        self.context_menu.addMenu(self.sub_menu)

        # Right click menu
        self.ui.layersShapesTreeView.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.ui.layersShapesTreeView.customContextMenuRequested.connect(self.displayContextMenu)

        # Not used for now, so hide them
        self.ui.startAtXLabel.hide()
        self.ui.startAtYLabel.hide()
        self.ui.unitLabel_1.hide()
        self.ui.unitLabel_2.hide()
        self.ui.startAtXLineEdit.hide()
        self.ui.startAtYLineEdit.hide()

        # Hidden until the loaded project contains break geometries
        self.updateBreaksPassWidget()

    def tr(self, string_to_translate):
        """
        Translate a string using the QCoreApplication translation framework
        @param: string_to_translate: a unicode string
        @return: the translated unicode string if it was possible to translate
        """
        return str(QtCore.QCoreApplication.translate('TreeHandler',
                                                           string_to_translate))

    def updateConfiguration(self):
        """
        This function should be called each time the configuration changes. It updates tools and custom actions in the treeView
        If a tool or a custom action disapear from the configuration, it is removed from the treeview
        """
        # Load the tools from the config file to the tool selection combobox
        #self.ui.layersShapesTreeView.clearSelection()
        self.ui.toolDiameterComboBox.blockSignals(True)
        default_tool = 1 # Tool 1 normally always exists
        current_tool = self.ui.toolDiameterComboBox.currentText()
        self.ui.toolDiameterComboBox.clear()
        for tool in g.config.vars.Tool_Parameters:
            self.ui.toolDiameterComboBox.addItem(tool)
        self.ui.toolDiameterComboBox.blockSignals(False)

        # Load the custom gcode names from the config file
        self.sub_menu.clear()
        for custom_action in g.config.vars.Custom_Actions:
            menu_action = self.sub_menu.addAction(custom_action.replace('_', ' '))
            menu_action.setData(custom_action)

        # update the items (if a tool or a custom_action disapeared from config file, we need to remove it in the treeview too)
        i = 0
        if self.layer_item_model: #  this is not set until buildLayerTree() is called
            i = self.layer_item_model.rowCount(QtCore.QModelIndex())

        while i > 0:
            i -= 1
            layer_item_index = self.layer_item_model.index(i, 0)

            if isValid(layer_item_index.data(LAYER_OBJECT)):
                real_layer = toPyObject(layer_item_index.data(LAYER_OBJECT))

                update_drawing = False
                if real_layer is not None and str(real_layer.tool_nr) not in g.config.vars.Tool_Parameters:
                    # The tool used for this layer doesn't exist anymore, we are going to replace it with the first tool
                    logger.warning(self.tr("Tool {0} used for \"{1}\" layer doesn't exist anymore in the configuration ; using tool {2} instead").format(real_layer.tool_nr, real_layer.name, default_tool))
                    # Update the layer's tool and repaint
                    UpdateLayerParameters().execute(
                        [real_layer], tool_nr=default_tool)
                    update_drawing = True

                if real_layer is not None\
                    and (real_layer.tool_diameter != g.config.vars.Tool_Parameters[str(real_layer.tool_nr)]['diameter']\
                      or real_layer.speed != g.config.vars.Tool_Parameters[str(real_layer.tool_nr)]['speed']\
                      or (not getattr(real_layer, 'lead_radius_overridden', False)\
                          and real_layer.lead_radius != g.config.vars.Tool_Parameters[str(real_layer.tool_nr)]['lead_radius'])\
                      or (not getattr(real_layer, 'lead_length_overridden', False)\
                          and real_layer.lead_length != g.config.vars.Tool_Parameters[str(real_layer.tool_nr)]['lead_length'])):
                    # The tool used for this layer exists, but its definition has changed, we need to update the layer
                    logger.warning(self.tr("Tool {0} used for \"{1}\" layer has changed, updating layer's data").format(real_layer.tool_nr, real_layer.name))
                    layer_values = {
                        "tool_diameter": g.config.vars.Tool_Parameters[
                            str(real_layer.tool_nr)]['diameter'],
                        "speed": g.config.vars.Tool_Parameters[
                            str(real_layer.tool_nr)]['speed'],
                    }
                    if not getattr(real_layer, 'lead_radius_overridden', False):
                        layer_values["lead_radius"] = g.config.vars.Tool_Parameters[
                            str(real_layer.tool_nr)]['lead_radius']
                    if not getattr(real_layer, 'lead_length_overridden', False):
                        layer_values["lead_length"] = g.config.vars.Tool_Parameters[
                            str(real_layer.tool_nr)]['lead_length']
                    UpdateLayerParameters().execute([real_layer], **layer_values)
                    update_drawing = True

                if real_layer is not None:
                    for shape in real_layer.shapes:
                        override = getattr(shape, "tool_override", None)
                        if override is not None:
                            number = override.tool_nr
                            if str(number) not in g.config.vars.Tool_Parameters:
                                number = default_tool
                            shape.tool_override = ToolSettings.from_profile(
                                number, g.config.vars.Tool_Parameters[str(number)])
                    # The lead in / lead out / overcut values of the layer are
                    # the global defaults, as long as they were not set by a
                    # layer name (those values must not be overwritten).
                    if update_lead_move_values(real_layer):
                        update_drawing = True
                    # The methods of the lead in and of the lead out are not
                    # copied into the layer: a layer which uses the
                    # configuration default follows the global default value.
                    # The drawing has to be repainted in any case, because the
                    # default methods may have changed.
                    update_drawing = True

                if update_drawing and g.window:
                    for shape in real_layer.shapes:
                        if isinstance(shape, Shape):
                            # Only repaint _real_ shapes (and not the custom GCode for example)
                            g.window.canvas_scene.repaint_shape(shape)
                    g.window.canvas_scene.update()

                # Assign the export order for the shapes of the layer "real_layer"
                for j in range(self.layer_item_model.rowCount(layer_item_index)):
                    shape_item_index = self.layer_item_model.index(j, 0, layer_item_index)

                    if isValid(shape_item_index.data(CUSTOM_GCODE_OBJECT)):
                        real_custom_action = toPyObject(shape_item_index.data(CUSTOM_GCODE_OBJECT))
                        if real_custom_action is not None and real_custom_action.name not in g.config.vars.Custom_Actions:
                            logger.warning(self.tr("Custom action \"{0}\" used for \"{1}\" layer doesn't exist anymore in the configuration, removing it").format(real_custom_action.name, real_layer.name))
                            self.removeCustomGCode(shape_item_index)

        # Reselect the previous tool and update the tool display for the _selected_ layers
        tool_index = self.ui.toolDiameterComboBox.findText(current_tool)
        logger.debug("reselecting tool : " + current_tool)
        if tool_index >= 0:
            self.ui.toolDiameterComboBox.setCurrentIndex(tool_index)
        else:
            self.ui.toolDiameterComboBox.setCurrentIndex(-1)
        self.updateToolParameters()


    def displayContextMenu(self, position):
        """
        Function used to display a right click context menu
        @param position: position of the cursor within the treeView widget
        """
        selected_action = self.context_menu.exec(self.ui.layersShapesTreeView.mapToGlobal(position))

        if selected_action and isValid(selected_action.data()):
            # contextual menu selection concerns a custom gcode
            custom_gcode_name = toPyObject(selected_action.data())

            self.addCustomGCodeAfter(custom_gcode_name)

    def _connectExpansionButtons(self, view, collapse_button, expand_button):
        """Use the same complete-folding contract for both tree views."""
        def update_buttons(can_collapse, can_expand):
            collapse_button.setEnabled(can_collapse)
            expand_button.setEnabled(can_expand)

        view.expansionAvailabilityChanged.connect(update_buttons)
        collapse_button.clicked.connect(view.collapseAll)
        expand_button.clicked.connect(view.expandAll)
        view.updateExpansionAvailability()

    def buildLayerTree(self, layers_list):
        """
        This method populates the Layers QTreeView with all the elements contained into the layers_list
        Method must be called each time a new .dxf file is loaded.
        options
        @param layers_list: list of the layers and shapes (created in the main)
        """
        self.layers_list = layers_list
        if self.layer_item_model:
            self.layer_item_model.clear()  # Remove any existing item_model
        self.layer_item_model = MyStandardItemModel()  # This is the container for the data (QStandardItemModel)
        self.layer_item_model.setHorizontalHeaderItem(0, QStandardItem(self.tr("[en]")))
        self.layer_item_model.setHorizontalHeaderItem(1, QStandardItem(self.tr("Name")))
        self.layer_item_model.setHorizontalHeaderItem(2, QStandardItem(self.tr("Nr")))
        self.layer_item_model.setHorizontalHeaderItem(3, QStandardItem(self.tr("Optimal path")))
        modele_root_element = self.layer_item_model.invisibleRootItem()  # Root element of our tree

        for layer in layers_list:
            icon = QIcon()
            icon.addPixmap(QPixmap(":/images/layer.png"))
            checkbox_element = QStandardItem(icon, "")
            checkbox_element.setData(QtCore.QVariant(layer), LAYER_OBJECT)  # store a ref in our treeView element
            modele_element = QStandardItem(layer.name)
            nbr_element = QStandardItem()
            optimise_element = QStandardItem()
            modele_root_element.appendRow([checkbox_element, modele_element, nbr_element, optimise_element])

            parent_item = modele_root_element.child(modele_root_element.rowCount() - 1, 0)
            containsChecked = False
            containsUnchecked = False
            containsTspChecked = False
            containsTspUnchecked = False
            for shape in layer.shapes:
                if isinstance(shape, CustomGCode):
                    self.AddCustomGCodeRowLayer(shape, parent_item)
                else:
                    self.AddShapeRowLayer(shape, parent_item)
                if shape.isDisabled():
                    containsUnchecked = True
                else:
                    containsChecked = True
                # The TSP checkbox exists only for real shapes (CustomGCode
                # rows have no "Optimal path" checkbox).
                if not isinstance(shape, CustomGCode):
                    if shape.isToolPathOptimized():
                        containsTspChecked = True
                    else:
                        containsTspUnchecked = True

            checkbox_element.setCheckState(self.getCheckState(containsChecked, containsUnchecked))
            checkbox_element.setFlags(QtCore.Qt.ItemFlag.ItemIsDragEnabled | QtCore.Qt.ItemFlag.ItemIsDropEnabled | QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            modele_element.setFlags(QtCore.Qt.ItemFlag.ItemIsDragEnabled | QtCore.Qt.ItemFlag.ItemIsDropEnabled | QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable)
            nbr_element.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            # "Optimal path" (TSP) checkbox on the layer row: it aggregates the
            # states of its shape children (PartiallyChecked when mixed), like
            # the enable/disable checkbox in column 0.
            optimise_element.setCheckState(self.getCheckState(containsTspChecked, containsTspUnchecked))
            optimise_element.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsUserCheckable)

        # Signal to get events when a checkbox state changes (enable or disable shapes)
        self.layer_item_model.itemChanged.connect(self.on_itemChanged)

        self.ui.layersShapesTreeView.setModel(self.layer_item_model)  # Affect our model to the GUI TreeView, in order to display it

        if g.config.vars.General['expand_layers_on_load']:
            self.ui.layersShapesTreeView.expandAll()
        else:
            self.ui.layersShapesTreeView.collapseAll()

        self.ui.layersShapesTreeView.setDragDropMode(QTreeView.DragDropMode.InternalMove)
        # self.ui.layersShapesTreeView.setDefaultDropAction(QtCore.Qt.MoveAction)
        # self.ui.layersShapesTreeView.setDragDropOverwriteMode(True)
        self.ui.layersShapesTreeView.setDropIndicatorShown(True)
        self.ui.layersShapesTreeView.setAcceptDrops(True)
        self.ui.layersShapesTreeView.setDragEnabled(True)

        for i in range(4):
            self.ui.layersShapesTreeView.resizeColumnToContents(i)

        # Show/hide the "Process breaks from" combobox for the new content
        self.updateBreaksPassWidget()

    def AddShapeRowLayer(self, shape, parent_item):
        icon = QIcon()
        icon.addPixmap(QPixmap(":/images/shape.png"))
        item_col_0 = QStandardItem(icon, "")
        item_col_0.setData(QVariantShape(shape), SHAPE_OBJECT)  # store a ref in our treeView element
        item_col_1 = QStandardItem(shape.type)
        item_col_2 = QStandardItem(str(shape.nr))
        item_col_3 = QStandardItem()
        parent_item.appendRow([item_col_0, item_col_1, item_col_2, item_col_3])

        # Deal with the checkboxes (shape enabled or disabled / send shape to TSP optimizer)
        item_col_0.setCheckState(QtCore.Qt.CheckState.Unchecked if shape.isDisabled() else QtCore.Qt.CheckState.Checked)
        item_col_3.setCheckState(QtCore.Qt.CheckState.Checked if shape.isToolPathOptimized() else QtCore.Qt.CheckState.Unchecked)

        flags = QtCore.Qt.ItemFlag.ItemIsDragEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable
        if shape.allowedToChange:
            flags |= QtCore.Qt.ItemFlag.ItemIsEnabled
        item_col_0.setFlags(flags | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
        item_col_1.setFlags(flags)
        item_col_2.setFlags(flags)
        item_col_3.setFlags(flags | QtCore.Qt.ItemFlag.ItemIsUserCheckable)

    def AddCustomGCodeRowLayer(self, custom_gcode, parent_item, push_row=None):
        icon = QIcon()
        icon.addPixmap(QPixmap(":/images/custom.png"))
        item_col_0 = QStandardItem(icon, "")  # will only display a checkbox + an icon that will never be disabled
        item_col_0.setData(QtCore.QVariant(custom_gcode), CUSTOM_GCODE_OBJECT)  # store a ref to the custom gcode in our treeView element
        item_col_1 = QStandardItem(custom_gcode.name)
        item_col_2 = QStandardItem(str(custom_gcode.nr))
        item_col_3 = QStandardItem()
        if push_row:
            parent_item.insertRow(push_row, [item_col_0, item_col_1, item_col_2, item_col_3])
        else:
            parent_item.appendRow([item_col_0, item_col_1, item_col_2, item_col_3])

        # Deal with the checkboxes (shape enabled or disabled / send shape to TSP optimizer)
        item_col_0.setCheckState(QtCore.Qt.CheckState.Unchecked if custom_gcode.isDisabled() else QtCore.Qt.CheckState.Checked)

        flags = QtCore.Qt.ItemFlag.ItemIsDragEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled
        item_col_0.setFlags(flags | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
        item_col_1.setFlags(flags)
        item_col_2.setFlags(flags)
        item_col_3.setFlags(flags)

    def buildEntitiesTree(self, entities_list):
        """
        This method populates the Entities (blocks) QTreeView with
        all the elements contained in the entities_list
        Method must be called each time a new .dxf file is loaded.
        options
        @param entities_list: list of the layers and shapes (created in the main)
        """

        self.entities_list = entities_list
        if self.entity_item_model:
            self.entity_item_model.clear()  # Remove any existing item_model
        self.entity_item_model = QStandardItemModel()
        self.entity_item_model.setHorizontalHeaderItem(0, QStandardItem(self.tr("[en]")))
        self.entity_item_model.setHorizontalHeaderItem(1, QStandardItem(self.tr("Name")))
        self.entity_item_model.setHorizontalHeaderItem(2, QStandardItem(self.tr("Nr")))
        self.entity_item_model.setHorizontalHeaderItem(3, QStandardItem(self.tr("Type")))
        self.entity_item_model.setHorizontalHeaderItem(4, QStandardItem(self.tr("Base point")))
        self.entity_item_model.setHorizontalHeaderItem(5, QStandardItem(self.tr("Scale")))
        self.entity_item_model.setHorizontalHeaderItem(6, QStandardItem(self.tr("Rotation")))
        modele_root_element = self.entity_item_model.invisibleRootItem()

        self.buildEntitiesSubTree(modele_root_element, entities_list)

        # Signal to get events when a checkbox state changes (enable or disable shapes)
        self.entity_item_model.itemChanged.connect(self.on_itemChanged)

        self.ui.entitiesTreeView.setModel(self.entity_item_model)

        self.ui.entitiesTreeView.expandToDepth(0)

        for i in range(6):
            self.ui.entitiesTreeView.resizeColumnToContents(i)

    def buildEntitiesSubTree(self, elements_model, elements_list):
        """
        This method is called (possibly recursively) to populate the
        Entities treeView. It is not intended to be called directly,
        use buildEntitiesTree() function instead.
        options
        @param elements_model: the treeView model (used to store the data, see QT docs)
        @param elements_list: either a list of entities, or a shape
        @return (containsChecked, containsUnchecked) indicating whether the subtree contains checked and/or unchecked elements
        """
        containsChecked = False
        containsUnchecked = False
        if isinstance(elements_list, list):
            # We got a list
            for element in elements_list:
                (checked, unchecked) = self.addEntitySubTree(elements_model, element)
                containsChecked = containsChecked or checked
                containsUnchecked = containsUnchecked or unchecked
        else:
            # Unique element (shape)
            element = elements_list
            containsChecked, containsUnchecked = self.addEntitySubTree(elements_model, element)
        return containsChecked, containsUnchecked

    def addEntitySubTree(self, elements_model, element):
        """
        This method populates a row of the Entities treeView. It is
        not intended to be called directly, use buildEntitiesTree()
        function instead.
        options
        @param elements_model: the treeView model (used to store the data, see QT docs)
        @param element: the Entity or Shape element
        @return (containsChecked, containsUnchecked) indicating whether the subtree contains checked and/or unchecked elements
        """
        containsChecked = False
        containsUnchecked = False
        item_col_0 = None
        if isinstance(element, EntityContent):
            icon = QIcon()
            icon.addPixmap(QPixmap(":/images/blocks.png"))
            item_col_0 = QStandardItem(icon, "")  # will only display a checkbox + an icon that will never be disabled
            item_col_0.setData(QtCore.QVariant(element), ENTITY_OBJECT)  # store a ref in our treeView element
            item_col_1 = QStandardItem(element.name)
            item_col_2 = QStandardItem(str(element.nr))
            item_col_3 = QStandardItem(self.tr("Entity"))
            item_col_4 = QStandardItem(str(element.p0))
            item_col_5 = QStandardItem(str(element.sca))
            item_col_6 = QStandardItem(str(round(degrees(element.rot), 3)))  # convert the angle into degrees with 3 digit after the decimal point
            elements_model.appendRow([item_col_0, item_col_1, item_col_2, item_col_3, item_col_4, item_col_5, item_col_6])

            for sub_element in element.children:
                (checked, unchecked) = self.buildEntitiesSubTree(item_col_0, sub_element)
                containsChecked = containsChecked or checked
                containsUnchecked = containsUnchecked or unchecked

            flags = QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled

        elif isinstance(element, Shape):
            icon = QIcon()
            icon.addPixmap(QPixmap(":/images/shape.png"), QIcon.Mode.Normal, QIcon.State.Off)
            item_col_0 = QStandardItem(icon, "")  # will only display a checkbox + an icon that will never be disabled
            item_col_0.setData(QVariantShape(element), SHAPE_OBJECT)  # store a ref in our treeView element
            item_col_1 = QStandardItem(element.type)
            item_col_2 = QStandardItem(str(element.nr))
            item_col_3 = QStandardItem(element.type)
            item_col_4 = QStandardItem()
            item_col_5 = QStandardItem()
            item_col_6 = QStandardItem()
            elements_model.appendRow([item_col_0, item_col_1, item_col_2, item_col_3, item_col_4, item_col_5, item_col_6])
            if element.isDisabled():
                containsUnchecked = True
            else:
                containsChecked = True

            flags = QtCore.Qt.ItemFlag.ItemIsSelectable
            if element.allowedToChange:
                flags |= QtCore.Qt.ItemFlag.ItemIsEnabled

        item_col_0.setCheckState(self.getCheckState(containsChecked, containsUnchecked))

        item_col_0.setFlags(flags | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
        item_col_1.setFlags(flags)
        item_col_2.setFlags(flags)
        item_col_3.setFlags(flags)
        item_col_4.setFlags(flags)
        item_col_5.setFlags(flags)
        item_col_6.setFlags(flags)

        return (containsChecked, containsUnchecked)

    def getCheckState(self, containsChecked, containsUnchecked):
        if containsChecked:
            if containsUnchecked:
                return QtCore.Qt.CheckState.PartiallyChecked
            else:
                return QtCore.Qt.CheckState.Checked
        else:
            return QtCore.Qt.CheckState.Unchecked

    def updateExportOrder(self, includeDisableds=False):
        """
        Update the layers_list order to reflect the TreeView order.
        This function must be called before generating the GCode
        (export function). Export will be performed in the order of the
        structure self.LayerContents of the main. Each layer contains
        some shapes, and the export order of the shapes is set by
        populating the exp_order[] list with the shapes reference number
        for each layer (eg exp_order = [5, 3, 2, 4, 0, 1] for layer 0,
        exp_order = [5, 3, 7] for layer 1, ...)
        options
        """

        i = self.layer_item_model.rowCount(QtCore.QModelIndex())
        while i > 0:
            i -= 1
            layer_item_index = self.layer_item_model.index(i, 0)

            if isValid(layer_item_index.data(LAYER_OBJECT)):
                real_layer = toPyObject(layer_item_index.data(LAYER_OBJECT))
                self.layers_list.remove(real_layer)  # Remove the layer from its original position
                self.layers_list.insert(0, real_layer)  # and insert it at the beginning of the layer's list

                real_layer.exp_order = []  # Clear the current export order
                real_layer.exp_order_complete = []  # Clear the current export order

                # Assign the export order for the shapes of the layer "real_layer"
                for j in range(self.layer_item_model.rowCount(layer_item_index)):
                    shape_item_index = self.layer_item_model.index(j, 0, layer_item_index)

                    real_shape = None
                    if isValid(shape_item_index.data(SHAPE_OBJECT)):
                        real_shape = toPyObject(shape_item_index.data(SHAPE_OBJECT)).shapeobj
                        if not real_shape.isDisabled() or includeDisableds:
                            real_layer.exp_order.append(real_shape.nr)  # Create the export order list with the real and unique shapes numbers (eg [25, 22, 30, 4, 1, 5])

                    if isValid(shape_item_index.data(CUSTOM_GCODE_OBJECT)):
                        real_shape = toPyObject(shape_item_index.data(CUSTOM_GCODE_OBJECT))

                    if real_shape and (not real_shape.isDisabled() or includeDisableds):
                        real_layer.exp_order_complete.append(real_layer.shapes.index(real_shape))  # Create the export order list with the shapes & custom gcode numbers (eg [5, 3, 2, 4, 0, 1])

    def updateTreeViewOrder(self):
        """
        Update the Layer TreeView order according to the exp_order list
        of each layer. This function should be called after running the
        TSP path otimizer
        """

        i = self.layer_item_model.rowCount(QtCore.QModelIndex())
        while i > 0:
            i -= 1
            layer_item_index = self.layer_item_model.index(i, 0)
            layer_item = self.layer_item_model.itemFromIndex(layer_item_index)

            if isValid(layer_item_index.data(LAYER_OBJECT)):
                real_layer = toPyObject(layer_item_index.data(LAYER_OBJECT))

                # for shape_nr in real_layer.exp_order[::-1]:  # reverse order and prepend if we want to insert optimized shape before fixed shapes
                for shape_nr in real_layer.exp_order:
                    for j in range(self.layer_item_model.rowCount(layer_item_index)):
                        shape_item_index = self.layer_item_model.index(j, 0, layer_item_index)

                        if isValid(shape_item_index.data(SHAPE_OBJECT)):
                            real_shape = toPyObject(shape_item_index.data(SHAPE_OBJECT)).shapeobj

                            if real_shape and real_shape.nr == shape_nr and (real_shape.send_to_TSP or g.config.vars.Route_Optimisation['TSP_shape_order'] == 'CONSTRAIN_ORDER_ONLY'):
                                # Shape number "shape_nr" found in the treeView and Shape is movable => moving it to its new position
                                item_to_be_moved = layer_item.takeRow(j)
                                layer_item.appendRow(item_to_be_moved)

                                break

    def columnsSelectDeselect(self, selection_model, item_index, select):
        """
        columnsSelectDeselect()
        """
        if select:
            # Select the matching shape in the list.
            selection_model.select(item_index, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        else:
            # Unselect the matching shape in the list.
            selection_model.select(item_index, QItemSelectionModel.SelectionFlag.Deselect | QItemSelectionModel.SelectionFlag.Rows)

    def updateShapeSelection(self, shape, select):
        """
        This method is a "slot" (callback) called from the main when the
        selection changes on the graphic view. It aims to update the
        treeView selection according to the graphic view.
        Note: in order to avoid signal loops, all selection signals are
        blocked when updating the selections in the treeViews
        options
        @param shape: the Shape whose selection has changed
        @param select: whether the Shape has been selected (True) or deselected (False)
        """
        # Layer treeView
        item_index = self.findLayerItemIndexFromShape(shape)
        selection_model = self.ui.layersShapesTreeView.selectionModel()  # Get the selection model of the QTreeView

        if item_index:
            # we found the matching index for the shape in our layers treeView model
            self.ui.layersShapesTreeView.blockSignals(True)  # Avoid signal loops (we dont want the treeView to re-emit selectionChanged signal)
            # setCurrentIndex also (re-)selects the item: do it first so
            # that the requested select/deselect state is the final one
            self.ui.layersShapesTreeView.setCurrentIndex(item_index)
            self.columnsSelectDeselect(selection_model, item_index, select)
            self.ui.layersShapesTreeView.blockSignals(False)

        # Entities treeView
        item_index = self.findEntityItemIndexFromShape(shape)
        selection_model = self.ui.entitiesTreeView.selectionModel()  # Get the selection model of the QTreeView

        if item_index:
            # we found the matching index for the shape in our entities treeView model
            self.ui.entitiesTreeView.blockSignals(True)  # Avoid signal loops (we dont want the treeView to re-emit selectionChanged signal)
            self.ui.entitiesTreeView.setCurrentIndex(item_index)
            self.columnsSelectDeselect(selection_model, item_index, select)
            self.ui.entitiesTreeView.blockSignals(False)

        # The canvas keeps its selection in the shapes themselves: mirror it
        # into the tree selection so that the tree selection always matches
        # the canvas selection (the parameter update slots apply the entered
        # value to the tree selection).
        self.updateSelection(self.ui.layersShapesTreeView)
        self.updateSelection(self.ui.entitiesTreeView)

        # Update the tool parameters fields of the whole selection
        self.clearToolsParameters()
        layers, shapes = self._selectedShapesAndLayers()
        if shapes or layers:
            self.displayToolParametersForSelection(layers, shapes)
        # else: nothing is selected - clearToolsParameters() above already
        # cleared the fields, so no values are shown.

    def updateShapeEnabling(self, shape, enable):
        """
        This method is a "slot" (callback) called from the main when the
        shapes are enabled or disabled on the graphic view.
        It aims to update the treeView checkboxes according to the
        graphic view.
        Note: in order to avoid signal loops, all selection signals are
        blocked when updating the checkboxes in the treeViews
        options
        @param shape: the Shape whose enabling has changed
        @param enable: whether the Shape has been enabled (True) or disabled (False)
        """
        # Layer treeView
        item_index = self.findLayerItemIndexFromShape(shape)

        if item_index:
            # we found the matching index for the shape in our treeView model
            item = item_index.model().itemFromIndex(item_index)

            self.layer_item_model.blockSignals(True)  # Avoid signal loops (we dont want the treeView to emit itemChanged signal)
            if enable:
                # Select the matching shape in the list
                self.updateCheckboxOfItem(item, QtCore.Qt.CheckState.Checked)

            else:
                # deselect the matching shape in the list
                self.updateCheckboxOfItem(item, QtCore.Qt.CheckState.Unchecked)

            self.layer_item_model.blockSignals(False)
            self.ui.layersShapesTreeView.update(item_index)  # update the treeList drawing
            self.traverseParentsAndUpdateEnableDisable(self.layer_item_model, item_index)  # update the parents checkboxes

            if self.auto_update_export_order:
                # update export order and thus export drawing
                self.prepareExportOrderUpdate()

        #Entities treeView
        item_index = self.findEntityItemIndexFromShape(shape)

        if item_index:
            # we found the matching index for the shape in our treeView model
            item = item_index.model().itemFromIndex(item_index)

            self.entity_item_model.blockSignals(True)  # Avoid signal loops (we dont want the treeView to emit itemChanged signal)
            if enable:
                # Select the matching shape in the list
                self.updateCheckboxOfItem(item, QtCore.Qt.CheckState.Checked)

            else:
                # deselect the matching shape in the list
                self.updateCheckboxOfItem(item, QtCore.Qt.CheckState.Unchecked)

            self.entity_item_model.blockSignals(False)
            self.ui.entitiesTreeView.update(item_index)  # update the treeList drawing
            self.traverseParentsAndUpdateEnableDisable(self.entity_item_model, item_index)  # update the parents checkboxes

        # The number of break geometries may have changed
        self.updateBreaksPassWidget()

    def findLayerItemIndexFromShape(self, shape):
        """
        Find internal layers treeView reference (item index) matching a
        "real" shape (ie a ShapeClass instance)
        options
        @param shape: the real shape (ShapeClass instance)
        @return: the found item index (can be None)
        """
        return self.traverseChildrenAndFindShape(self.layer_item_model, QtCore.QModelIndex(), shape)

    def findEntityItemIndexFromShape(self, shape):
        """
        Find internal entities treeView reference (item index) matching
        a "real" shape (ie a ShapeClass instance)
        options
        @param shape: the real shape (ShapeClass instance)
        @return: the found item index (can be None)
        """
        return self.traverseChildrenAndFindShape(self.entity_item_model, QtCore.QModelIndex(), shape)

    def traverseChildrenAndFindShape(self, item_model, item_index, shape):
        """
        This method is used by the findLayerItemIndexFromShape() and
        findEntityItemIndexFromShape() function in order to find a
        reference from a layer. It traverses the QT model and compares
        each item data with the shape passed as parameter. When found,
        the reference is returned
        options
        @param item_model: the treeView model (used to store the data, see QT docs)
        @param item_index: the initial model index (QModelIndex) in the tree (all children of this index are scanned)
        @param shape: the real shape (ShapeClass instance)
        @return: the found item index
        """
        for i in range(item_model.rowCount(item_index)):
            sub_item_index = item_model.index(i, 0, item_index)

            if isValid(sub_item_index.data(SHAPE_OBJECT)):
                real_item = toPyObject(sub_item_index.data(SHAPE_OBJECT)).shapeobj
                if shape == real_item:
                    return sub_item_index

            if item_model.hasChildren(sub_item_index):
                found_item_index = self.traverseChildrenAndFindShape(item_model, sub_item_index, shape)
                if found_item_index:
                    return found_item_index

    def traverseChildrenAndSelect(self, item_model, item_index, state):
        """
        This method is used internally to select/deselect all children
        of a given entity (eg to select all the shapes of a given layer
        when the user has selected a layer)
        options
        @param item_model: the treeView model (used to store the data, see QT docs)
        @param item_index: the initial model index (QModelIndex) in the tree (all children of this index are scanned)
        @param select: whether to select (True) or not (False)
        """
        for i in range(item_model.rowCount(item_index)):
            sub_item_index = item_model.index(i, 0, item_index)

            if item_model.hasChildren(sub_item_index):
                self.traverseChildrenAndSelect(item_model, sub_item_index, state)
            else:
                element = sub_item_index.model().itemFromIndex(sub_item_index)
                if element:
                    if element.data(SHAPE_OBJECT):
                        self.setShapeSelected(
                            toPyObject(element.data(SHAPE_OBJECT)).shapeobj,
                            state)
                    elif element.data(CUSTOM_GCODE_OBJECT):
                        toPyObject(element.data(CUSTOM_GCODE_OBJECT)).setSelected (state)

    def traverseChildrenAndEnableDisable(self, item_model, item_index, checked_state):
        """
        This method is used internally to check/uncheck all children of
        a given entity (eg to enable all shapes of a given layer when
        the user has enabled a layer)
        options
        @param item_model: the treeView model (used to store the data, see QT docs)
        @param item_index: the initial model index (QModelIndex) in the tree (all children of this index are scanned)
        @param checked_state: the state of the checkbox
        """

        for i in range(item_model.rowCount(item_index)):
            sub_item_index = item_model.index(i, 0, item_index)

            if item_model.hasChildren(sub_item_index):
                self.traverseChildrenAndEnableDisable(item_model, sub_item_index, checked_state)

            item = item_model.itemFromIndex(sub_item_index)
            if item and item.isEnabled():  # FIXME when parent was partially checked and a child cannot be checked
                self.updateCheckboxOfItem(item, checked_state)

    def traverseParentsAndUpdateEnableDisable(self, item_model, item_index):
        """
        This code updates the parents checkboxes for a given entity.
        Parents checkboxes are tristate, eg if some of the shapes that
        belong to a layer are checked and others not, then the checkbox
        of this layer will be "half" checked
        options
        @param item_model: the treeView model (used to store the data, see QT docs)
        @param item_index: the initial model index (QModelIndex) in the tree (all children of this index are scanned)
        """
        has_unchecked = False
        has_partially_checked = False
        has_checked = False
        item = None
        parent_item_index = None

        for i in range(item_model.rowCount(item_index.parent())):
            parent_item_index = item_model.index(i, 0, item_index.parent())

            item = item_model.itemFromIndex(parent_item_index)
            if item:
                if item.checkState() == QtCore.Qt.CheckState.Checked:
                    has_checked = True
                elif item.checkState() == QtCore.Qt.CheckState.PartiallyChecked:
                    has_partially_checked = True
                else:
                    has_unchecked = True

        # Update the parent item according to its children
        if item and item.parent():
            parent_state = item.parent().checkState()
            if has_checked and has_unchecked or has_partially_checked:
                parent_state = QtCore.Qt.CheckState.PartiallyChecked
            elif has_checked and not has_unchecked:
                parent_state = QtCore.Qt.CheckState.Checked
            elif not has_checked and has_unchecked:
                parent_state = QtCore.Qt.CheckState.Unchecked

            self.updateCheckboxOfItem(item.parent(), parent_state)

            # Handle the parent of the parent (recursive call)
            if isValid(parent_item_index.parent()):
                self.traverseParentsAndUpdateEnableDisable(item_model, parent_item_index.parent())

    def _fill_lead_mode_combo(self, combo, lead_in=False):
        """
        Fill a combobox with the methods of the lead in / lead out.

        The data of the entries is the method itself, so that the
        translation of the labels does not matter.
        @param combo: the combobox
        @param lead_in: whether the combobox is for the lead in (True) or for
                the lead out (False)
        """
        combo.clear()
        for mode, label in self._lead_mode_items(lead_in=lead_in):
            combo.addItem(label, mode)
        combo.setCurrentIndex(-1)

    def _lead_mode_items(self, lead_in=False):
        """
        The methods of the lead in / lead out with their (translated) labels.

        The configuration default is not an entry of the list: the combobox
        always shows the method which is really used (the value of the
        configuration file if the layer does not have its own value).

        The 'radius' method is not selectable for the lead in: with the
        internal cutter compensation (and with G40) it is the same as the
        'startmove' method, so it is merged into it. It is only selectable for
        the lead out (where the build up movement is not needed).

        @param lead_in: whether the items are for the lead in (True) or for
                the lead out (False)
        @return: a list of (method, label) tuples
        """
        labels = lead_mode_labels()
        items = [(LEAD_OFF, labels[LEAD_OFF]),
                 (LEAD_STRAIGHT, labels[LEAD_STRAIGHT]),
                 (LEAD_STARTMOVE, labels[LEAD_STARTMOVE])]
        if not lead_in:
            items.append((LEAD_RADIUS, labels[LEAD_RADIUS]))
        return items

    def _lead_in_items(self):
        """The items of the lead in combobox."""
        return self._lead_mode_items(lead_in=True)

    def _lead_out_items(self):
        """The items of the lead out combobox."""
        return self._lead_mode_items(lead_in=False)

    def _map_lead_in_mode(self, mode):
        """
        The method which is really used for the lead in: the 'radius' method
        is not selectable any more, it is the same as the 'startmove' method
        with the internal cutter compensation (and with G40).
        @param mode: the method of the layer
        @return: the method
        """
        return LEAD_STARTMOVE if mode == LEAD_RADIUS else mode

    def _update_lead_mode_combo(self, combo, modes, lead_in=False):
        """
        Show the method of the selected layers in a combobox. If the layers
        use different methods, the entry "Different" is shown.

        The 'radius' method is not selectable for the lead in (it is merged
        into the 'startmove'): a layer which still has the 'radius' method
        (from an old project or a layer name identifier) shows the
        'startmove' method instead.
        @param combo: the combobox
        @param modes: the methods of the selected layers
        @param lead_in: whether the combobox is for the lead in (True) or for
                the lead out (False)
        """
        if lead_in:
            modes = [self._map_lead_in_mode(mode) for mode in modes]
        unique = set(modes)
        combo.blockSignals(True)
        try:
            combo.clear()
            if len(unique) > 1:
                combo.addItem(self.tr("Different"), None)
            for mode, label in self._lead_mode_items(lead_in=lead_in):
                combo.addItem(label, mode)
            if len(unique) == 1:
                index = combo.findData(modes[0])
            else:
                index = 0
            combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            combo.blockSignals(False)

    def _selected_layers(self):
        """
        The layers of the current selection.
        @return: a list of layer contents
        """
        layers = []
        selected_indexes_list = self.ui.layersShapesTreeView.selectedIndexes()
        for model_index in selected_indexes_list:
            if not isValid(model_index):
                continue
            model_index = model_index.sibling(model_index.row(), 0)
            element = model_index.model().itemFromIndex(model_index)
            if not element:
                continue
            real_item = None
            if isValid(element.data(SHAPE_OBJECT)):
                real_item = toPyObject(element.data(SHAPE_OBJECT)).shapeobj.parentLayer
            elif isValid(element.data(LAYER_OBJECT)):
                real_item = toPyObject(element.data(LAYER_OBJECT))
            if real_item is not None and real_item not in layers:
                layers.append(real_item)
        return layers

    def _fill_overcut_combo(self, combo):
        """
        Fill the combobox of the overcut with the possible settings.

        The data of the entries is the setting itself, so that the
        translation of the labels does not matter.
        @param combo: the combobox
        """
        combo.clear()
        for state, label in self._overcut_items():
            combo.addItem(label, state)
        combo.setCurrentIndex(-1)

    def _overcut_items(self):
        """
        The possible settings of the overcut with their (translated) labels.

        The configuration default is not an entry of the list: the combobox
        always shows the setting which is really used (the value of the
        configuration file if the layer does not have its own value).
        @return: a list of (setting, label) tuples
        """
        return [(OVERCUT_OFF, self.tr("None")),
                (OVERCUT_ON, self.tr("Overcut"))]

    def _update_overcut_combo(self, combo, states):
        """
        Show the setting of the selected layers in the combobox. If the layers
        use different settings, the entry "Different" is shown.
        @param combo: the combobox
        @param states: the settings of the selected layers
        """
        unique = set(states)
        combo.blockSignals(True)
        try:
            combo.clear()
            if len(unique) > 1:
                combo.addItem(self.tr("Different"), None)
            for state, label in self._overcut_items():
                combo.addItem(label, state)
            if len(unique) == 1:
                index = combo.findData(states[0])
            else:
                index = 0
            combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            combo.blockSignals(False)

    def overcutUpdate(self, index=None):
        """
        Slot of the "Overcut" combobox: the overcut is changed for the closed
        contours of the current selection.

        The overcut is a setting of the shape. It is only possible for closed
        contours: open contours are ignored (they are neither changed nor
        reported as an error). In a mixed selection (open and closed contours,
        which can live in the same layer) the setting is therefore applied to
        the closed contours only.

        @param index: the index of the activated combobox entry
        """
        if index is None:
            index = self.ui.overcutComboBox.currentIndex()
        state = self.ui.overcutComboBox.itemData(index)
        if state is None:
            # The "Different" entry: it is only a display of the selection.
            return
        # If the setting is the one of the configuration file, the shapes
        # follow the standard again.
        if state == self._global_overcut_state():
            state = OVERCUT_DEFAULT
        shapes = self._closed_contours_of_selection()
        if not shapes:
            return
        SetShapeOvercut().execute(
            shapes, state, use_default=(state == OVERCUT_DEFAULT))
        # Repaint the shapes of the layers of the changed contours (the layer
        # holds the open contours too, so they are repainted as well).
        repainted = []
        for shape in shapes:
            layer = getattr(shape, 'parentLayer', None)
            for member in getattr(layer, 'shapes', [shape]):
                if isinstance(member, Shape) and member not in repainted:
                    repainted.append(member)
                    g.window.canvas_scene.repaint_shape(member)
        if g.window and g.window.canvas_scene:
            g.window.canvas_scene.update()

    def _selection_has_closed_contour(self, shapes, layers):
        """
        Whether the given selection contains at least one closed contour.

        The overcut is only possible for closed contours, so the combobox is
        disabled if the selection consists of open contours only.
        @param shapes: the selected shapes
        @param layers: the selected layers
        @return: True if a closed contour is part of the selection
        """
        shapes = list(shapes) if shapes else []
        if shapes:
            return any(getattr(shape, 'closed', False) for shape in shapes)
        # The selection may consist of layer rows only: use the shapes of the
        # layers then.
        for layer in layers:
            for shape in getattr(layer, 'shapes', []):
                if getattr(shape, 'closed', False):
                    return True
        return False

    def _closed_contours_of_selection(self):
        """
        The closed contours of the current selection.

        The overcut is a setting of the shape, so in a mixed selection only
        the closed contours are changed.
        @return: a list of shapes
        """
        layers, shapes = self._selectedShapesAndLayers()
        result = [shape for shape in shapes
                  if getattr(shape, 'closed', False)]
        if result:
            return result
        # The selection may consist of layer rows only: use the closed
        # contours of the layers then.
        if shapes:
            # Shapes are selected but none of them is closed.
            return []
        for layer in layers:
            for shape in getattr(layer, 'shapes', []):
                if getattr(shape, 'closed', False) and shape not in result:
                    result.append(shape)
        return result

    def _effective_overcut_state(self, item):
        """
        The overcut setting which is really used for the given shape or layer:
        the own value or the value of the configuration file.
        @param item: the shape or the layer content
        @return: OVERCUT_ON or OVERCUT_OFF
        """
        getter = getattr(item, 'get_overcut_enabled', None)
        if getter is not None:
            return OVERCUT_ON if getter() else OVERCUT_OFF
        return self._global_overcut_state()

    def _lead_display_contours(self):
        """
        The contours (shapes) of the current selection whose lead in / lead
        out / overcut is shown and changed.

        The settings belong to the shape, so the shapes of the selection are
        used. If only layer rows are selected, all the shapes of the layers
        are used.
        @return: a list of shapes
        """
        shapes = [shape for shape in self.display_tool_shapes
                  if isinstance(shape, Shape)]
        if shapes:
            return shapes
        contours = []
        for layer in self.display_tool_layers:
            for shape in getattr(layer, 'shapes', []):
                if isinstance(shape, Shape) and shape not in contours:
                    contours.append(shape)
        return contours

    def _overcut_display_values(self):
        """
        The overcut values shown by the combobox.

        The overcut is a setting of the closed contours, so the values of the
        closed contours of the selection are shown (the open contours are
        ignored). If only layer rows are selected, the values of the layers
        are shown.
        @return: (effective_states, own_values)
        """
        contours = self._lead_display_contours()
        shapes = [shape for shape in contours
                  if getattr(shape, 'closed', False)]
        if shapes:
            return ([self._effective_overcut_state(shape) for shape in shapes],
                    [getattr(shape, 'overcut_enabled', OVERCUT_DEFAULT)
                     for shape in shapes])
        if contours:
            # Open contours only: the combobox is disabled and shows "None".
            return [OVERCUT_OFF], [OVERCUT_DEFAULT]
        layers = self.display_tool_layers
        return ([self._effective_overcut_state(layer) for layer in layers],
                [getattr(layer, 'overcut_enabled', OVERCUT_DEFAULT)
                 for layer in layers])

    def _global_overcut_state(self):
        """
        The overcut setting of the configuration file: the state which the
        layers follow if they do not have their own value.
        @return: OVERCUT_ON or OVERCUT_OFF
        """
        try:
            enabled = g.config.vars.Lead_In_Out['overcut_enabled']
        except (KeyError, AttributeError):
            enabled = False
        return OVERCUT_ON if enabled else OVERCUT_OFF

    def _lead_mode_update(self, attribute, index):
        """
        Apply the method which is selected in a combobox to all the selected
        shapes (each contour has its own lead in / lead out).

        If the selected method is the one of the configuration file, the
        shapes follow the standard again (like the milling depth: only the
        shapes which were changed have their own value).

        @param attribute: the attribute of the shape ('lead_in_mode' or
                         'lead_out_mode')
        @param index: the index of the activated combobox entry
        """
        combo = (self.ui.leadInComboBox if attribute == 'lead_in_mode'
                 else self.ui.leadOutComboBox)
        mode = combo.itemData(index)
        if mode is None:
            # The "Different" entry: it is only a display of the selection.
            return
        try:
            standard = g.config.vars.Lead_In_Out[attribute]
        except (KeyError, AttributeError):
            standard = None
        if mode == standard:
            # The value of the configuration file: the shape follows the
            # standard again.
            mode = LEAD_DEFAULT
        shapes = self._lead_display_contours()
        if not shapes:
            return
        SetShapeLeadMode().execute(
            shapes, attribute, mode, use_default=(mode == LEAD_DEFAULT))
        # Repaint the shapes of the layers of the changed contours.
        repainted = []
        for shape in shapes:
            layer = getattr(shape, 'parentLayer', None)
            for member in getattr(layer, 'shapes', [shape]):
                if isinstance(member, Shape) and member not in repainted:
                    repainted.append(member)
                    g.window.canvas_scene.repaint_shape(member)
        if g.window and g.window.canvas_scene:
            g.window.canvas_scene.update()
        self._update_lead_parameter_relevance(shapes)

    def leadInUpdate(self, index=None):
        """
        Slot of the "Lead in" combobox: the method of the lead in of all the
        selected layers is changed.
        @param index: the index of the activated combobox entry
        """
        if index is None:
            index = self.ui.leadInComboBox.currentIndex()
        self._lead_mode_update('lead_in_mode', index)

    def leadOutUpdate(self, index=None):
        """
        Slot of the "Lead out" combobox: the method of the lead out of all
        the selected layers is changed.
        @param index: the index of the activated combobox entry
        """
        if index is None:
            index = self.ui.leadOutComboBox.currentIndex()
        self._lead_mode_update('lead_out_mode', index)

    def toolUpdate(self):
        """Apply a tool only to the selected shapes or explicit layer rows."""
        text = self.ui.toolDiameterComboBox.currentText()
        if not text:
            return
        number, valid = toInt(text)
        if not valid:
            return
        _, shapes = self._selectedShapesAndLayers()
        explicit_layers = []
        for index in self.ui.layersShapesTreeView.selectedIndexes():
            item = index.model().itemFromIndex(index.sibling(index.row(), 0))
            layer = item.data(LAYER_OBJECT) if item is not None else None
            if layer is not None and layer not in explicit_layers:
                explicit_layers.append(layer)
        profile = g.config.vars.Tool_Parameters[str(number)]
        if not shapes and not explicit_layers:
            self._refresh_tool_values()
            return
        changed = AssignTool().execute(shapes, explicit_layers, number, profile)
        window = getattr(g, "window", None)
        scene = getattr(window, "canvas_scene", None)
        if scene is not None:
            for shape in changed:
                shape.toolpath_plan = None
                scene.repaint_shape(shape)
            scene.update()
        self.updateToolParameters()

    def toolParameterzRetractionArealUpdate(self):
        """
        Slot that updates the above tools parameter when the
        corresponding LineEdit changes
        @param text: the value of the LineEdit
        """
        self.ui.zRetractionArealLineEdit.setPalette(self.palette)  # Restore color

        # Get the new value and convert it to float
        val = toFloat(self.ui.zRetractionArealLineEdit.text())
        if val[1]:
            selected_indexes_list = self.ui.layersShapesTreeView.selectedIndexes()

            for model_index in selected_indexes_list:
                if isValid(model_index):
                    model_index = model_index.sibling(model_index.row(), 0)  # get the first column of the selected row, since it's the only one that contains data
                    element = model_index.model().itemFromIndex(model_index)
                    real_item = None
                    if isValid(element.data(SHAPE_OBJECT)):
                        real_item = toPyObject(element.data(SHAPE_OBJECT)).shapeobj.parentLayer  # Shape has no such property => update the parent layer
                    elif isValid(element.data(LAYER_OBJECT)):
                        real_item = toPyObject(element.data(LAYER_OBJECT))
                    if real_item is not None:
                        UpdateLayerParameters().execute(
                            [real_item], axis3_retract=val[0])
                        self.axis3_retract = real_item.axis3_retract

    def toolParameterzSafetyMarginUpdate(self):
        """
        Slot that updates the above tools parameter when the
        corresponding LineEdit changes
        @param text: the value of the LineEdit
        """
        self.ui.zSafetyMarginLineEdit.setPalette(self.palette)  # Restore color

        # Get the new value and convert it to float
        val = toFloat(self.ui.zSafetyMarginLineEdit.text())
        if val[1]:
            selected_indexes_list = self.ui.layersShapesTreeView.selectedIndexes()

            for model_index in selected_indexes_list:
                if isValid(model_index):
                    model_index = model_index.sibling(model_index.row(), 0)  # get the first column of the selected row, since it's the only one that contains data
                    element = model_index.model().itemFromIndex(model_index)
                    real_item = None
                    if isValid(element.data(SHAPE_OBJECT)):
                        real_item = toPyObject(element.data(SHAPE_OBJECT)).shapeobj.parentLayer
                    elif isValid(element.data(LAYER_OBJECT)):
                        real_item = toPyObject(element.data(LAYER_OBJECT))
                    if real_item is not None:
                        UpdateLayerParameters().execute(
                            [real_item], axis3_safe_margin=val[0])
                        self.axis3_safe_margin = real_item.axis3_safe_margin

    def toolParameterzInfeedDepthUpdate(self):
        """
        Slot that updates the above tools parameter when the
        corresponding LineEdit changes
        @param text: the value of the LineEdit
        """
        self.ui.zInfeedDepthLineEdit.setPalette(self.palette)  # Restore color

        # Get the new value and convert it to float
        val = toFloat(self.ui.zInfeedDepthLineEdit.text())
        if val[1]:
            selected_indexes_list = self.ui.layersShapesTreeView.selectedIndexes()

            for model_index in selected_indexes_list:
                if isValid(model_index):
                    model_index = model_index.sibling(model_index.row(), 0)  # get the first column of the selected row, since it's the only one that contains data
                    element = model_index.model().itemFromIndex(model_index)
                    if isValid(element.data(SHAPE_OBJECT)):
                        real_item = toPyObject(element.data(SHAPE_OBJECT)).shapeobj
                        if UpdateShapeParameters().execute(
                                [real_item], "axis3_slice_depth", val[0]):
                            self.axis3_slice_depth = real_item.axis3_slice_depth
                            g.window.canvas_scene.repaint_shape(real_item)
            self.prepareExportOrderUpdate()
            self.updateBreaksPassWidget()
            g.window.canvas_scene.update()

    def toolParameterg1FeedXYUpdate(self):
        """
        Slot that updates the above tools parameter when the
        corresponding LineEdit changes
        @param text: the value of the LineEdit
        """
        self.ui.g1FeedXYLineEdit.setPalette(self.palette)  # Restore color

        # Get the new value and convert it to float
        val = toFloat(self.ui.g1FeedXYLineEdit.text())
        if val[1]:
            selected_indexes_list = self.ui.layersShapesTreeView.selectedIndexes()

            for model_index in selected_indexes_list:
                if isValid(model_index):
                    model_index = model_index.sibling(model_index.row(), 0)  # get the first column of the selected row, since it's the only one that contains data
                    element = model_index.model().itemFromIndex(model_index)
                    if isValid(element.data(SHAPE_OBJECT)):
                        real_item = toPyObject(element.data(SHAPE_OBJECT)).shapeobj
                        UpdateShapeParameters().execute(
                            [real_item], "f_g1_plane", val[0])
                        self.f_g1_plane = real_item.f_g1_plane

    def toolParameterg1FeedZUpdate(self):
        """
        Slot that updates the above tools parameter when the
        corresponding LineEdit changes
        @param text: the value of the LineEdit
        """
        self.ui.g1FeedZLineEdit.setPalette(self.palette)  # Restore color

        # Get the new value and convert it to float
        val = toFloat(self.ui.g1FeedZLineEdit.text())
        if val[1]:
            selected_indexes_list = self.ui.layersShapesTreeView.selectedIndexes()

            for model_index in selected_indexes_list:
                if isValid(model_index):
                    model_index = model_index.sibling(model_index.row(), 0)  # get the first column of the selected row, since it's the only one that contains data
                    element = model_index.model().itemFromIndex(model_index)
                    if isValid(element.data(SHAPE_OBJECT)):
                        real_item = toPyObject(element.data(SHAPE_OBJECT)).shapeobj
                        UpdateShapeParameters().execute(
                            [real_item], "f_g1_depth", val[0])
                        self.f_g1_depth = real_item.f_g1_depth

    def toolParameterzInitialMillDepthUpdate(self):
        """
        Slot that updates the above tools parameter when the
        corresponding LineEdit changes
        @param text: the value of the LineEdit
        """
        self.ui.zInitialMillDepthLineEdit.setPalette(self.palette)  # Restore color

        # Get the new value and convert it to float
        val = toFloat(self.ui.zInitialMillDepthLineEdit.text())
        if val[1]:
            selected_indexes_list = self.ui.layersShapesTreeView.selectedIndexes()

            for model_index in selected_indexes_list:
                if isValid(model_index):
                    model_index = model_index.sibling(model_index.row(), 0)  # get the first column of the selected row, since it's the only one that contains data
                    element = model_index.model().itemFromIndex(model_index)
                    if isValid(element.data(SHAPE_OBJECT)):
                        real_item = toPyObject(element.data(SHAPE_OBJECT)).shapeobj
                        if UpdateShapeParameters().execute(
                                [real_item], "axis3_start_mill_depth", val[0]):
                            self.axis3_start_mill_depth = real_item.axis3_start_mill_depth
                            g.window.canvas_scene.repaint_shape(real_item)
            self.prepareExportOrderUpdate()
            self.updateBreaksPassWidget()
            g.window.canvas_scene.update()

    def toolParameterzFinalMillDepthUpdate(self):
        """
        Slot that updates the above tools parameter when the
        corresponding LineEdit changes
        @param text: the value of the LineEdit
        """
        self.ui.zFinalMillDepthLineEdit.setPalette(self.palette)  # Restore color

        # Get the new value and convert it to float
        val = toFloat(self.ui.zFinalMillDepthLineEdit.text())
        if val[1]:
            selected_indexes_list = self.ui.layersShapesTreeView.selectedIndexes()

            for model_index in selected_indexes_list:
                if isValid(model_index):
                    model_index = model_index.sibling(model_index.row(), 0)  # get the first column of the selected row, since it's the only one that contains data
                    element = model_index.model().itemFromIndex(model_index)
                    if isValid(element.data(SHAPE_OBJECT)):
                        real_item = toPyObject(element.data(SHAPE_OBJECT)).shapeobj
                        if UpdateShapeParameters().execute(
                                [real_item], "axis3_mill_depth", val[0]):
                            self.axis3_mill_depth = real_item.axis3_mill_depth
                            g.window.canvas_scene.repaint_shape(real_item)
            self.prepareExportOrderUpdate()
            self.updateBreaksPassWidget()
            g.window.canvas_scene.update()
            
    def toolParameterMillingOffsetUpdate(self):
        """
        Slot that updates the individual additional offset (finishing
        allowance) of the selected shapes when the corresponding LineEdit
        changes
        """
        self.ui.millingOffsetLineEdit.setPalette(self.palette)  # Restore color

        # Get the new value and convert it to float
        val = toFloat(self.ui.millingOffsetLineEdit.text())
        if val[1]:
            selected_indexes_list = self.ui.layersShapesTreeView.selectedIndexes()

            for model_index in selected_indexes_list:
                if isValid(model_index):
                    model_index = model_index.sibling(model_index.row(), 0)  # get the first column of the selected row, since it's the only one that contains data
                    element = model_index.model().itemFromIndex(model_index)
                    if isValid(element.data(SHAPE_OBJECT)):
                        real_item = toPyObject(element.data(SHAPE_OBJECT)).shapeobj
                        if UpdateShapeParameters().execute(
                                [real_item], "milling_offset", val[0]):
                            self.milling_offset = real_item.milling_offset
                            g.window.canvas_scene.repaint_shape(real_item)
            self.prepareExportOrderUpdate()
            g.window.canvas_scene.update()

    @staticmethod
    def setShapeSelected(shape, selected):
        """Synchronize a domain selection with its optional 2D item."""
        scene = getattr(g.window, 'canvas_scene', None)
        if scene is not None and hasattr(scene, 'set_shape_selected'):
            scene.set_shape_selected(shape, selected)
        else:
            shape.setSelected(selected)

    @staticmethod
    def setShapeDisabled(shape, disabled):
        """Synchronize a domain enabled state with its optional 2D item."""
        scene = getattr(g.window, 'canvas_scene', None)
        if scene is not None and hasattr(scene, 'set_shape_disabled'):
            scene.set_shape_disabled(shape, disabled)
        else:
            shape.setDisable(disabled)

    def actionOnSelectionChange(self, parent, selected, deselected):
        """
        This function is a callback called from QTreeView class when
        something changed in the selection. It aims to update the
        graphic view according to the tree selection. It also deals
        with children selection when a parent is selected
        Note that there is no predefined signal for
        selectionChange event, that's why we use a callback function
        options
        @param parent: QT parent item (unused)
        @param select: list of selected items in the treeView
        @param deselect: list of deselected items in the treeView
        """
        if not self.ui.layersShapesTreeView.selectionModel():
            return

        # if invoked from updateSelection() do nothing
        if hasattr (self, "updateSelectionInProgress"):
            return

        self.clearToolsParameters()  # disable tools parameters widgets, ...

        # Deselects all the shapes that are selected
        for selection in deselected:
            for model_index in selection.indexes():
                if isValid(model_index):
                    element = model_index.model().itemFromIndex(model_index)
                    if element:
                        if isValid(element.data(SHAPE_OBJECT)):
                            # Deselect the shape on the canvas
                            self.setShapeSelected(
                                toPyObject(element.data(SHAPE_OBJECT)).shapeobj,
                                False)

                        elif isValid(element.data(CUSTOM_GCODE_OBJECT)):
                            toPyObject(element.data(CUSTOM_GCODE_OBJECT)).setSelected(False)

                        elif isValid(element.data(LAYER_OBJECT)):
                            self.traverseChildrenAndSelect(self.layer_item_model, model_index, False)

                        elif isValid(element.data(ENTITY_OBJECT)):
                            self.traverseChildrenAndSelect(self.entity_item_model, model_index, False)

        # Selects all the shapes that are selected
        lastSelected = None
        for selection in selected:
            for model_index in selection.indexes():
                if isValid(model_index):
                    model_index = model_index.sibling(model_index.row(), 0)  # get the first column of the selected row, since it's the only one that contains data
                    element = model_index.model().itemFromIndex(model_index)
                    if element:
                        if isValid(element.data(SHAPE_OBJECT)):
                            lastSelected = toPyObject(element.data(SHAPE_OBJECT)).shapeobj
                            self.setShapeSelected(lastSelected, True)

                        elif isValid(element.data(CUSTOM_GCODE_OBJECT)):
                            lastSelected = toPyObject(element.data(CUSTOM_GCODE_OBJECT))
                            lastSelected.setSelected(True)  # Select the shape on the canvas

                        # select all the children of a given layer when clicked
                        elif isValid(element.data(LAYER_OBJECT)):
                            self.traverseChildrenAndSelect(self.layer_item_model, model_index, True)
                            lastSelected = toPyObject(element.data(LAYER_OBJECT))

                        # select all the children of a given entity when clicked
                        elif isValid(element.data(ENTITY_OBJECT)):
                            self.traverseChildrenAndSelect(self.entity_item_model, model_index, True)

        # Update tree selection for both layer and entity pages
        self.updateSelection(self.ui.layersShapesTreeView)
        self.updateSelection(self.ui.entitiesTreeView)

        # Show the parameters of the whole CURRENT selection (not only of the
        # last clicked item / the selection delta) so that mixed values are
        # detected and displayed.
        layers, shapes = self._selectedShapesAndLayers()
        if shapes or layers:
            self.displayToolParametersForSelection(layers, shapes)

        if g.window.canvas_scene:
            g.window.canvas_scene.update()

    def updateSelection(self, treeview):
        """
        Update selection of all tree items in a tree view according to value of
        .selected field of the object that corresponds to this tree item.

        This is called after massive item selections/deselections.
        """

        model = treeview.model()
        item_sel = QItemSelection()
        item_desel = QItemSelection()

        for branch in range(model.rowCount()):
            self.updateSelectionRecursive(model, model.index(branch, 0), item_sel, item_desel)

        # Block actionOnSelectionChange to avoid unselecting whole blocks
        # (because they are part of item_desel).
        self.updateSelectionInProgress = True
        selection = treeview.selectionModel()
        selection.select(item_sel, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        selection.select(item_desel, QItemSelectionModel.SelectionFlag.Deselect | QItemSelectionModel.SelectionFlag.Rows)

        del self.updateSelectionInProgress

    def updateSelectionRecursive(self, model, root, item_sel, item_desel):
        """
        Helper routine for updateSelection() used for recursion
        """
        if model.hasChildren(root):
            # always unselect layer and entity rows, otherwise selection misbehaves
            item_desel.select(root, root)
            for branch in range(model.rowCount(root)):
                self.updateSelectionRecursive(model, model.index(branch, 0, root), item_sel, item_desel)
        else:
            if isValid(root.data(SHAPE_OBJECT)):
                if toPyObject(root.data(SHAPE_OBJECT)).shapeobj.isSelected():
                    item_sel.select(root, root)
                else:
                    item_desel.select(root, root)
            elif isValid(root.data(CUSTOM_GCODE_OBJECT)):
                if toPyObject(root.data(CUSTOM_GCODE_OBJECT)).isSelected():
                    item_sel.select(root, root)
                else:
                    item_desel.select(root, root)

    def clearToolsParameters(self):
        """
        This function restore defaults for tools parameters widgets
        (disabled, default color, ...)
        """
        number_of_selected_items = len(self.ui.layersShapesTreeView.selectedIndexes())

        if number_of_selected_items <= 2:  # 2 selections = 1 row of 2 columns
            # 0 or 1 row are selected => clear some states
            self.tool_nr = None
            self.tool_diameter = None
            self.speed = None
            self.lead_radius = None
            self.lead_length = None
            self.axis3_retract = None
            self.axis3_safe_margin = None
            self.axis3_slice_depth = None
            self.axis3_start_mill_depth = None
            self.axis3_mill_depth = None
            self.milling_offset = None
            self.f_g1_plane = None
            self.f_g1_depth = None

            self.ui.toolDiameterComboBox.setPalette(self.palette)
            self.ui.toolDiameterLabel.setPalette(self.palette)
            self.ui.toolSpeedLabel.setPalette(self.palette)
            self.ui.leadRadiusLabel.setPalette(self.palette)
            self.ui.leadLengthLabel.setPalette(self.palette)
            self.ui.zRetractionArealLineEdit.setPalette(self.palette)
            self.ui.zSafetyMarginLineEdit.setPalette(self.palette)
            self.ui.zInfeedDepthLineEdit.setPalette(self.palette)
            self.ui.g1FeedXYLineEdit.setPalette(self.palette)
            self.ui.g1FeedZLineEdit.setPalette(self.palette)
            self.ui.zInitialMillDepthLineEdit.setPalette(self.palette)
            self.ui.zFinalMillDepthLineEdit.setPalette(self.palette)
            self.ui.millingOffsetLineEdit.setPalette(self.palette)

        if number_of_selected_items == 0:
            for combo in (self.ui.toolDiameterComboBox,
                          self.ui.leadInComboBox, self.ui.leadOutComboBox,
                          self.ui.overcutComboBox):
                combo.setPlaceholderText("")
                combo.setCurrentIndex(-1)
            # Nothing is selected: no values are shown at all. This makes the
            # behaviour of the tool and the shape fields consistent (also
            # directly after startup, before anything is loaded).
            for widget in self._mill_parameter_widgets():
                widget.setText("")
            self.ui.millSettingsFrame.setEnabled(False)

        else:
            self.ui.millSettingsFrame.setEnabled(True)

    def updateBreaksPassWidget(self):
        """
        Updates the "Process breaks from" combobox: it is shown only when
        break geometries exist. When a shape is selected, the combobox is
        filled with one entry per actually generated milling pass of that
        shape ("Last pass", "0 - never" and "Pass 1..n"). The selection of
        the shape is restored; an explicit pass that exceeds the current
        number of passes is reset to the default "Last pass" (this reset is
        visible in the combobox and logged).
        """
        visible = break_geometries_present()
        label = getattr(self.ui, 'breaksPassLabel', None)
        combo = getattr(self.ui, 'breaksPassComboBox', None)
        if label is None or combo is None:
            return
        label.setVisible(visible)
        combo.setVisible(visible)
        if not visible:
            return

        shape_item = getattr(self, 'display_tool_shape', None)
        if not isinstance(shape_item, Shape):
            combo.setEnabled(False)
            return

        combo.setEnabled(True)
        n_passes = len(shape_item.get_pass_depths())
        break_pass = getattr(shape_item, 'break_pass', -1)
        if break_pass not in (-1, 0) and break_pass > n_passes:
            break_pass = -1
            SetShapeBreakPass().execute([shape_item], -1)
            logger.warning(self.tr(
                "Break pass selection reset to 'Last pass': the shape "
                "generates only %d passes") % n_passes)

        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem(self.tr("Last pass (default)"), -1)
            combo.addItem(self.tr("0 - never"), 0)
            for nr in range(1, n_passes + 1):
                combo.addItem(self.tr("Pass %d") % nr, nr)
            index = combo.findData(break_pass)
            combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            combo.blockSignals(False)

    def breaksPassUpdate(self, index=None):
        """
        Slot of the "Process breaks from" combobox. Applies the selected
        value (-1 = last pass, 0 = never, 1..n = pass number) to all
        selected shapes and updates the export route.
        @param index: the index of the activated combobox entry
        """
        if index is None:
            index = self.ui.breaksPassComboBox.currentIndex()
        if index < 0:
            return
        value = self.ui.breaksPassComboBox.itemData(index)
        if value is None:
            return

        selected_shapes = []
        selected_indexes_list = self.ui.layersShapesTreeView.selectedIndexes()
        for model_index in selected_indexes_list:
            if isValid(model_index):
                model_index = model_index.sibling(model_index.row(), 0)
                element = model_index.model().itemFromIndex(model_index)
                if isValid(element.data(SHAPE_OBJECT)):
                    real_item = toPyObject(element.data(SHAPE_OBJECT)).shapeobj
                    if real_item not in selected_shapes:
                        selected_shapes.append(real_item)
        SetShapeBreakPass().execute(selected_shapes, int(value))
        self.prepareExportOrderUpdate()

    def _selectedShapesAndLayers(self):
        """
        @return (layers, shapes) of the CURRENT tree selection.

        The selection is read from the tree (and not from the change delta
        of the selection callback) so that a multiple selection is complete
        and mixed parameter values can be detected reliably.
        """
        layers = []
        shapes = []
        selection_model = self.ui.layersShapesTreeView.selectionModel()
        if selection_model is None:
            return layers, shapes
        for model_index in selection_model.selectedIndexes():
            if not isValid(model_index):
                continue
            model_index = model_index.sibling(model_index.row(), 0)
            element = model_index.model().itemFromIndex(model_index)
            if element is None:
                continue
            if isValid(element.data(SHAPE_OBJECT)):
                shape = toPyObject(element.data(SHAPE_OBJECT)).shapeobj
                if isinstance(shape, Shape):
                    if shape not in shapes:
                        shapes.append(shape)
                    layer = getattr(shape, 'parentLayer', None)
                    if layer is not None and layer not in layers:
                        layers.append(layer)
            elif isValid(element.data(LAYER_OBJECT)):
                layer = toPyObject(element.data(LAYER_OBJECT))
                if layer not in layers:
                    layers.append(layer)
                for shape in getattr(layer, 'shapes', None) or []:
                    if isinstance(shape, Shape) and shape not in shapes:
                        shapes.append(shape)
        # The canvas keeps its selection in the shapes themselves (and not
        # only in the tree): include those, otherwise a selection made on
        # the canvas would be incomplete and mixed values would not be
        # detected.
        for shape in self._allShapesInTree():
            if shape.isSelected() and shape not in shapes:
                shapes.append(shape)
                layer = getattr(shape, 'parentLayer', None)
                if layer is not None and layer not in layers:
                    layers.append(layer)
        return layers, shapes

    def _allShapesInTree(self):
        """
        @return every Shape object of the layer tree
        """
        shapes = []
        model = self.layer_item_model
        if model is None:
            return shapes
        for branch in range(model.rowCount()):
            self._collectShapesRecursive(model, model.index(branch, 0), shapes)
        return shapes

    def _collectShapesRecursive(self, model, root, shapes):
        """
        Helper for _allShapesInTree() used for recursion
        """
        if model.hasChildren(root):
            for branch in range(model.rowCount(root)):
                self._collectShapesRecursive(
                    model, model.index(branch, 0, root), shapes)
        elif isValid(root.data(SHAPE_OBJECT)):
            shape = toPyObject(root.data(SHAPE_OBJECT)).shapeobj
            if isinstance(shape, Shape) and shape not in shapes:
                shapes.append(shape)

    def updateToolParameters(self):
        """
        Refresh the mill settings frame for the current selection.

        The current tree selection is used, so a refresh can never fall
        back to the value of a single shape while several shapes are
        selected (that would hide the mixed state).
        """
        layers, shapes = self._selectedShapesAndLayers()
        if shapes or layers:
            self.displayToolParametersForSelection(layers, shapes)
        else:
            # Nothing is selected: no values are shown (never fall back to the
            # values of a previously selected shape/layer).
            self.clearToolsParameters()

    def displayToolParametersForItem(self, layer_item, shape_item = None):
        """
        Display the current tools settings (fill the QLineEdit, ...)
        for a single Layer / Shape (thin wrapper around the selection
        display so that both paths share the same central logic)
        @param layer_item: layer instance as defined in LayerContent.py
        @param shape_item: shape instance as defined in Shape.py
        """
        if isinstance(shape_item, Shape):
            layers = [layer_item if layer_item is not None
                      else getattr(shape_item, "parentLayer", None)]
            self.displayToolParametersForSelection(layers, [shape_item])
        else:
            self.displayToolParametersForSelection(
                [layer_item] if layer_item is not None else [], [])

    # ------------------------------------------------------------------
    # Mill settings frame: central parameter handling
    # ------------------------------------------------------------------
    @staticmethod
    def _tool_parameter_default(item, key):
        """
        Tool default (from the Tools table) that applies to a shape/layer.
        """
        layer = effective_tool(item) or item
        tool_nr = str(getattr(layer, "tool_nr", 1))
        try:
            return float(g.config.vars.Tool_Parameters[tool_nr][key])
        except Exception:
            return None

    def _mill_parameter_fields(self):
        """
        Central description of the mill settings parameters.

        Each entry is (attribute, widget, on_layer, default getter, tooltip):
        the default getter returns the value the item would get from the
        global configuration or from its own tool, so that shapes with
        different tools are handled correctly.
        @return the list of parameter descriptions
        """
        def config_default(section, key):
            def getter(item):
                return float(g.config.vars[section][key])
            return getter

        def tool_default(key):
            return lambda item: self._tool_parameter_default(item, key)

        return [
            ("tool_diameter", self.ui.toolDiameterLabel, True,
             tool_default("diameter"),
             self.tr("Diameter of the tool used for this layer."
                     " [mm] Defined in the Tools table.")),
            ("speed", self.ui.toolSpeedLabel, True,
             tool_default("speed"),
             self.tr("Spindle speed of the tool. [rpm]"
                     " Defined in the Tools table.")),
            ("lead_radius", self.ui.leadRadiusLabel, True,
             tool_default("lead_radius"),
             self.tr("Common radius at the workpiece of the lead in and of"
                     " the lead out. [mm] Defined in the Tools table. It"
                     " has to be greater than the radius of the tool.")),
            ("lead_length", self.ui.leadLengthLabel, True,
             tool_default("lead_length"),
             self.tr("Common length of the straight lead in and of the"
                     " straight lead out, measured along the contour"
                     " direction. [mm] Defined in the Tools table.")),
            ("overcut_length", self.ui.overcutLengthLabel, True,
             tool_default("overcut_length"),
             self.tr("Length of the overcut, measured along the contour."
                     " [mm] Defined in the Tools table.")),
            ("axis3_retract", self.ui.zRetractionArealLineEdit, True,
             config_default("Depth_Coordinates", "axis3_retract"),
             self.tr("Z retraction plane: height the tool moves to before"
                     " a rapid move (G0). [mm] Larger values lift the"
                     " tool higher.")),
            ("axis3_safe_margin", self.ui.zSafetyMarginLineEdit, True,
             config_default("Depth_Coordinates", "axis3_safe_margin"),
             self.tr("Z safety margin: distance above the workpiece top"
                     " used for rapid moves. [mm]")),
            ("axis3_start_mill_depth", self.ui.zInitialMillDepthLineEdit,
             False,
             config_default("Depth_Coordinates", "axis3_start_mill_depth"),
             self.tr("Z workpiece top: Z coordinate of the workpiece"
                     " surface. [mm] All cutting depths are measured"
                     " relative to it.")),
            ("axis3_slice_depth", self.ui.zInfeedDepthLineEdit, False,
             config_default("Depth_Coordinates", "axis3_slice_depth"),
             self.tr("Z infeed depth: maximum depth removed per pass in"
                     " Z direction. [mm] Smaller values create more"
                     " passes.")),
            ("axis3_mill_depth", self.ui.zFinalMillDepthLineEdit, False,
             config_default("Depth_Coordinates", "axis3_mill_depth"),
             self.tr("Z final mill depth: final Z target of the milling"
                     " of this shape. [mm] Absolute Z value; a more"
                     " negative value mills deeper.")),
            ("milling_offset", self.ui.millingOffsetLineEdit, False,
             tool_default("milling_offset"),
             None),  # tooltip is defined in the .ui form (translated)
            ("f_g1_plane", self.ui.g1FeedXYLineEdit, False,
             config_default("Feed_Rates", "f_g1_plane"),
             self.tr("XY feed rate for cutting moves in the XY plane."
                     " [mm/min]")),
            ("f_g1_depth", self.ui.g1FeedZLineEdit, False,
             config_default("Feed_Rates", "f_g1_depth"),
             self.tr("Z feed rate for cutting moves in Z direction."
                     " [mm/min]")),
        ]

    def _mill_parameter_widgets(self):
        """
        @return the widgets of all mill settings parameters
        """
        return [field[1] for field in self._mill_parameter_fields()]

    def setupMillParameterTooltips(self):
        """
        Give every visible mill settings parameter a helpful tooltip
        (meaning, unit and effect of the parameter).
        """
        for attribute, widget, on_layer, default_getter, tooltip in \
                self._mill_parameter_fields():
            if tooltip:
                widget.setToolTip(tooltip)
        self.ui.toolDiameterComboBox.setToolTip(self.tr(
            "Tool used for this layer. Diameter, speed, start radius and"
            " additional offset are defined per tool in the Tools table."))

    @staticmethod
    def _gray_palette(palette):
        """
        De-emphasize the text of a parameter widget (standard value or
        mixed state). Both text roles are set so that line edits and
        labels are shown in grey.
        """
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText):
            palette.setColor(role, QtCore.Qt.GlobalColor.gray)
        return palette

    def _set_parameter_widget(self, widget, state, value, standard):
        """
        Show one parameter state in its widget (single central styling).
        A standard value stays fully usable and is only de-emphasized;
        a mixed/unavailable state shows a placeholder that never parses as
        a number, so it can not be written back into a shape.
        """
        palette = QPalette(self.palette)
        if state == sps.SAME:
            widget.setText(str(round(value, 4)))
            if standard:
                self._gray_palette(palette)
            widget.setPalette(palette)
            widget.setEnabled(True)
        elif state == sps.MIXED:
            widget.setText(self.tr("Different"))
            self._gray_palette(palette)
            widget.setPalette(palette)
            widget.setEnabled(True)
        elif state == sps.UNAVAILABLE:
            # the parameter is not available for a part of the selection:
            # never apply a value to the shapes that do not support it
            widget.setText(self.tr("Different"))
            self._gray_palette(palette)
            widget.setPalette(palette)
            widget.setEnabled(False)
        else:
            widget.setText("")
            widget.setPalette(palette)
            widget.setEnabled(False)

    def _de_emphasize_standard(self, widget, values, default):
        """
        De-emphasize a combobox which shows the standard of the configuration
        file: the value is not an own value of the layer, a change of the
        standard is applied to it.
        @param widget: the combobox
        @param values: the own values of the selected layers
        @param default: the value which means "the standard of the
               configuration file"
        """
        palette = QPalette(self.palette)
        if all(value == default for value in values):
            self._gray_palette(palette)
        widget.setPalette(palette)

    def _refresh_tool_values(self):
        """
        Show the parameter values of the currently selected tool and always
        de-emphasize (gray) them: they can only be changed through the tool
        selection (the dropdown), never directly in this frame, so they must
        never look editable and must stay gray independent of the contour
        selection.
        """
        tool_nr = self.ui.toolDiameterComboBox.currentText()
        if not self.ui.layersShapesTreeView.selectedIndexes():
            # Nothing is selected: the tool values are only meaningful for a
            # selected shape/layer, so no values are shown (this also keeps the
            # startup state empty).
            for widget in (self.ui.toolDiameterLabel, self.ui.toolSpeedLabel,
                           self.ui.leadRadiusLabel, self.ui.leadLengthLabel,
                           self.ui.overcutLengthLabel):
                widget.setText("")
            return
        try:
            params = g.config.vars.Tool_Parameters[str(tool_nr)]
        except Exception:
            params = None
        fields = (("diameter", self.ui.toolDiameterLabel, 3),
                  ("speed", self.ui.toolSpeedLabel, 1),
                  ("lead_radius", self.ui.leadRadiusLabel, 3),
                  ("lead_length", self.ui.leadLengthLabel, 3),
                  ("overcut_length", self.ui.overcutLengthLabel, 3))
        palette = QPalette(self.palette)
        self._gray_palette(palette)
        for key, widget, digits in fields:
            combo = self.ui.toolDiameterComboBox
            if combo.currentIndex() < 0 and combo.placeholderText():
                widget.setText("\u2014")
            elif params is not None:
                try:
                    widget.setText(str(round(float(params[key]), digits)))
                except Exception:
                    widget.setText("")
            widget.setPalette(palette)

    def _update_lead_parameter_relevance(self, contours):
        """
        De-emphasize the common radius and the common length if none of the
        selected methods needs them: the values are kept, but they are not
        used for the movements.
        @param contours: the selected shapes (or layers)
        """
        modes = []
        for item in contours or []:
            modes.append(item.get_lead_in_mode())
            modes.append(item.get_lead_out_mode())
        needs_radius = any(mode_needs_radius(mode) for mode in modes)
        needs_length = any(mode_needs_length(mode) for mode in modes)
        for widget, needed in ((self.ui.leadRadiusLabel, needs_radius),
                               (self.ui.leadLengthLabel, needs_length)):
            palette = QPalette(self.palette)
            if not needed:
                self._gray_palette(palette)
            widget.setPalette(palette)

    def displayToolParametersForSelection(self, layers, shapes):
        """
        Show the parameters of the whole selection (single or multiple).

        Equal values are shown normally (standard values de-emphasized),
        parameters with different values show the placeholder "Different".
        The placeholder is an indication only and is never stored or passed
        to the milling calculation (it is not a number).
        @param layers: layers of the selection (layer/tool parameters)
        @param shapes: selected shapes (shape parameters)
        """
        self.display_tool_layers = list(layers)
        self.display_tool_shapes = list(shapes)
        self.display_tool_layer = (self.display_tool_layers[0]
                                   if self.display_tool_layers else None)
        self.display_tool_shape = (self.display_tool_shapes[0]
                                   if self.display_tool_shapes else None)

        tool_items = ([effective_tool(shape) for shape in shapes]
                      if shapes else self.display_tool_layers)
        layer_item = tool_items[0] if tool_items else None
        if layer_item is not None:
            tool_numbers = set(getattr(tool, "tool_nr", None)
                               for tool in tool_items)
            combo = self.ui.toolDiameterComboBox
            if len(tool_numbers) > 1:
                combo.setPlaceholderText(self.tr("Different tools"))
                combo.setCurrentIndex(-1)
                self.tool_nr = None
            else:
                combo.setPlaceholderText("")
                combo.setCurrentIndex(combo.findText(str(layer_item.tool_nr)))
                self.tool_nr = layer_item.tool_nr
            combo.setPalette(self.palette)

        for attribute, widget, on_layer, default_getter, tooltip in \
                self._mill_parameter_fields():
            items = (self.display_tool_layers if on_layer
                     else self.display_tool_shapes)
            state, value = sps.parameter_state(items, attribute)
            standard = (state == sps.SAME and
                        sps.is_standard_value(items, attribute, default_getter))
            self._set_parameter_widget(widget, state, value, standard)
            # keep the state used by the update slots / paint routines
            setattr(self, attribute, value if state == sps.SAME else None)

        # The methods of the lead in, of the lead out and the overcut are
        # settings of the shape (each contour has its own). The combobox shows
        # the method which is really used (the value of the configuration file
        # if the shape does not have its own value).
        contours = self._lead_display_contours()
        if contours:
            self._update_lead_mode_combo(
                self.ui.leadInComboBox,
                [shape.get_lead_in_mode() for shape in contours],
                lead_in=True)
            self._update_lead_mode_combo(
                self.ui.leadOutComboBox,
                [shape.get_lead_out_mode() for shape in contours],
                lead_in=False)
            overcut_states, overcut_own = self._overcut_display_values()
            self._update_overcut_combo(
                self.ui.overcutComboBox, overcut_states)
            self.ui.leadInComboBox.setEnabled(True)
            self.ui.leadOutComboBox.setEnabled(True)
            # The overcut is only possible for closed contours: the combobox
            # is disabled (greyed) if the selection holds open contours only.
            self.ui.overcutComboBox.setEnabled(
                self._selection_has_closed_contour(self.display_tool_shapes,
                                                   self.display_tool_layers))
            # A value which is the standard of the configuration file is
            # de-emphasized (it is not an own value of the shape). The 'radius'
            # method of the lead in is not selectable any more: it is mapped
            # to the 'startmove' method.
            self._de_emphasize_standard(
                self.ui.leadInComboBox,
                [self._map_lead_in_mode(
                     getattr(shape, 'lead_in_mode', LEAD_DEFAULT))
                 for shape in contours], LEAD_DEFAULT)
            self._de_emphasize_standard(
                self.ui.leadOutComboBox,
                [getattr(shape, 'lead_out_mode', LEAD_DEFAULT)
                 for shape in contours], LEAD_DEFAULT)
            self._de_emphasize_standard(
                self.ui.overcutComboBox, overcut_own, OVERCUT_DEFAULT)
        else:
            self._update_lead_mode_combo(self.ui.leadInComboBox,
                                         [LEAD_OFF], lead_in=True)
            self._update_lead_mode_combo(self.ui.leadOutComboBox,
                                         [LEAD_OFF], lead_in=False)
            self._update_overcut_combo(self.ui.overcutComboBox,
                                       [OVERCUT_OFF])
            self.ui.leadInComboBox.setEnabled(False)
            self.ui.leadOutComboBox.setEnabled(False)
            self.ui.overcutComboBox.setEnabled(False)

        # The parameters which are not needed by the selected methods are
        # de-emphasized: their value is kept, but it is not used.
        self._update_lead_parameter_relevance(contours)

        # The tool values are always shown de-emphasized (they are changed
        # only through the tool selection).
        self._refresh_tool_values()

        self.updateBreaksPassWidget()

    def updatePocketMill(self, shape_item, enable):
        """
        This method is a "slot" (callback) called from the main when the
        Pocket Mill is enabled or disabled on the graphic view.
        It aims to update the Mill Settings Frame according to the
        graphic view.
        
        @param enable: whether the Shape has been enabled (True) or disabled (False)
        """
        
        """if(enable):
            self.ui.OffsetXYLineEdit.setEnabled(True)
            self.OffsetXY = self.updateAndColorizeWidget(self.ui.OffsetXYLineEdit,
                                                       self.OffsetXY,
                                                       shape_item.OffsetXY)
        else:
            self.ui.OffsetXYLineEdit.setEnabled(False)
            self.OffsetXY = self.updateAndColorizeWidget(self.ui.OffsetXYLineEdit,
                                                       self.OffsetXY,
                                                       shape_item.OffsetXY)
        """
        
    def updateDrill(self, shape_item, enable):
        """
        This method is a "slot" (callback) called from the main when the
        Drill is enabled or disabled on the graphic view.
        It aims to update the Mill Settings Frame according to the
        graphic view.
        
        @param enable: whether the Shape has been enabled (True) or disabled (False)
        """
        
        """
        if(enable):
            self.ui.OffsetXYLineEdit.setEnabled(False)
            self.ui.g1FeedXYLineEdit.setEnabled(False)
            #self.OffsetXY = self.updateAndColorizeWidget(self.ui.OffsetXYLineEdit,
            #                                           self.OffsetXY,
            #                                           shape_item.OffsetXY)
        else:
            self.ui.g1FeedXYLineEdit.setEnabled(True)
            #self.OffsetXY = self.updateAndColorizeWidget(self.ui.OffsetXYLineEdit,
            #                                           self.OffsetXY,
            #                                           shape_item.OffsetXY)
        """

    def updateAndColorizeWidget(self, widget, previous_value, value):
        """
        This function colours the text in grey when two values are
        different. It is used to show differences in tools settings
        when several layers / shapes are selected.
        @param widget: QT widget to update (can be a QLabel or a QLineEdit)
        @param previous_value: the value of the previously selected item
        @param value: the value (parameter) of the selected item
        """
        widget.setText(str(round(value, 4)))  # Round the value with at most 4 digits

        if previous_value and value != previous_value:
            # Several different tools parameter are currently selected (eg: mill deph = -3 for the first selected item and -2 for the second) => grey color for the text
            palette = QPalette()
            self._gray_palette(palette)
            widget.setPalette(palette)

        widget.setEnabled(True)

        return value

    def disableSelectedItems(self):
        selected_indexes_list = self.ui.layersShapesTreeView.selectedIndexes()

        for model_index in selected_indexes_list:
            if isValid(model_index):
                model_index = model_index.sibling(model_index.row(), 0)
                element = model_index.model().itemFromIndex(model_index)
                if element.isEnabled():
                    element.setCheckState(QtCore.Qt.CheckState.Unchecked)

    def enableSelectedItems(self):
        selected_indexes_list = self.ui.layersShapesTreeView.selectedIndexes()

        for model_index in selected_indexes_list:
            if isValid(model_index):
                model_index = model_index.sibling(model_index.row(), 0)
                element = model_index.model().itemFromIndex(model_index)
                if element.isEnabled():
                    element.setCheckState(QtCore.Qt.CheckState.Checked)

    def doNotOptimizeRouteForSelectedItems(self):
        selected_indexes_list = self.ui.layersShapesTreeView.selectedIndexes()

        for model_index in selected_indexes_list:
            if isValid(model_index):
                model_index = model_index.sibling(model_index.row(), PATH_OPTIMISATION_COL)
                element = model_index.model().itemFromIndex(model_index)
                if element.isEnabled():
                    element.setCheckState(QtCore.Qt.CheckState.Unchecked)

    def optimizeRouteForSelectedItems(self):
        selected_indexes_list = self.ui.layersShapesTreeView.selectedIndexes()

        for model_index in selected_indexes_list:
            if isValid(model_index):
                model_index = model_index.sibling(model_index.row(), PATH_OPTIMISATION_COL)
                element = model_index.model().itemFromIndex(model_index)
                if element.isEnabled():
                    element.setCheckState(QtCore.Qt.CheckState.Checked)

    def actionOnKeyPress(self, event):
        """
        This function is a callback called from QTreeView class when a
        key is pressed on the treeView. If the key is the spacebar, and O, then
        capture it to enable/disable shape and optimize path ...
        @param key_code: the key code as defined by QT
        @param item_index: the item on which the keyPress event occurred
        """

        # Enable/disable checkbox
        if event.key() == QtCore.Qt.Key.Key_Space:
            for layer in self.layers_list:
                for shape in layer.shapes:
                    if shape.isSelected():
                        sub_item_index = self.findLayerItemIndexFromShape(shape)
                        # Get the first column of the row (ie the one that contains the enable/disable checkbox)
                        sub_item_index = sub_item_index.sibling(sub_item_index.row(), 0)
                        sub_item = sub_item_index.model().itemFromIndex(sub_item_index)
                        if sub_item.isEnabled():
                            # Toggle checkbox
                            sub_item.setCheckState(QtCore.Qt.CheckState.Unchecked if sub_item.checkState() == QtCore.Qt.CheckState.Checked else QtCore.Qt.CheckState.Checked)

        # Optimize path checkbox
        elif event.key() == QtCore.Qt.Key.Key_O:
            # Collect the affected checkboxes first, then apply ONE uniform
            # target state to all of them: inverting each item individually
            # would leave a mixed multi-selection mixed and would disable an
            # already enabled shape when more shapes are selected.
            sub_items = []
            for layer in self.layers_list:
                for shape in layer.shapes:
                    if shape.isSelected():
                        sub_item_index = self.findLayerItemIndexFromShape(shape)
                        # Get the column of the row that contains the "Optimize Path" checkbox
                        sub_item_index = sub_item_index.sibling(sub_item_index.row(), PATH_OPTIMISATION_COL)
                        sub_item = sub_item_index.model().itemFromIndex(sub_item_index)
                        if sub_item.isEnabled():
                            sub_items.append(sub_item)

            target_checked = next_group_check_state(
                [it.checkState() == QtCore.Qt.CheckState.Checked
                 for it in sub_items])
            new_state = (QtCore.Qt.CheckState.Checked if target_checked
                         else QtCore.Qt.CheckState.Unchecked)
            for sub_item in sub_items:
                sub_item.setCheckState(new_state)
        else:
            return False
        return True

    def _pathOptimisationItemsForChange(self, item):
        """
        Return the column-3 items to which a change of the Path Optimisation
        (TSP) checkbox applies: the whole current selection if the changed row
        is part of a multi-row shape selection, otherwise only the changed
        item.
        @param item: the column-3 item whose check state changed
        """
        model = item.model()
        clicked = item.index().sibling(item.row(), PATH_OPTIMISATION_COL)
        view = getattr(self.ui, "layersShapesTreeView", None)
        selected_items = []
        if view is not None and model is self.layer_item_model:
            for sel_index in view.selectedIndexes():
                if not isValid(sel_index):
                    continue
                col0_item = model.itemFromIndex(sel_index.sibling(sel_index.row(), 0))
                if col0_item is not None and isValid(col0_item.data(SHAPE_OBJECT)):
                    col3_item = model.itemFromIndex(
                        sel_index.sibling(sel_index.row(), PATH_OPTIMISATION_COL))
                    if col3_item is not None:
                        selected_items.append(col3_item)
        if len(selected_items) > 1 and any(
                it.index() == clicked for it in selected_items):
            return selected_items
        return [model.itemFromIndex(clicked)]

    def _pathOptimisationChildItems(self, model, parent_index):
        """
        Return the column-3 (Optimal path) items of all shape rows below
        parent_index (recursive). Used to apply a layer row's target state to
        every shape child.
        """
        items = []
        for row in range(model.rowCount(parent_index)):
            child0_index = model.index(row, 0, parent_index)
            child0_item = model.itemFromIndex(child0_index)
            if child0_item is not None and isValid(child0_item.data(SHAPE_OBJECT)):
                col3_item = model.itemFromIndex(
                    child0_index.sibling(child0_index.row(), PATH_OPTIMISATION_COL))
                if col3_item is not None:
                    items.append(col3_item)
            if model.hasChildren(child0_index):
                items.extend(self._pathOptimisationChildItems(model, child0_index))
        return items

    def _updatePathOptimisationParentState(self, item):
        """
        Recompute the aggregated "Optimal path" (TSP) state of the parent row
        (layer/entity) from its shape children after a child changed:
        all on -> Checked, all off -> Unchecked, mixed -> PartiallyChecked.
        @param item: a shape's column-3 item
        """
        model = item.model()
        col0_index = item.index().sibling(item.row(), 0)
        parent_col0_index = col0_index.parent()
        if not parent_col0_index.isValid():
            return
        contains_checked = False
        contains_unchecked = False
        for row in range(model.rowCount(parent_col0_index)):
            child0_item = model.itemFromIndex(
                model.index(row, 0, parent_col0_index))
            if child0_item is None:
                continue
            obj = child0_item.data(SHAPE_OBJECT)
            if isValid(obj):
                if toPyObject(obj).shapeobj.isToolPathOptimized():
                    contains_checked = True
                else:
                    contains_unchecked = True
        parent_col3_index = model.index(parent_col0_index.row(),
                                        PATH_OPTIMISATION_COL,
                                        parent_col0_index.parent())
        parent_col3_item = model.itemFromIndex(parent_col3_index)
        if parent_col3_item is not None:
            model.blockSignals(True)
            try:
                parent_col3_item.setCheckState(
                    self.getCheckState(contains_checked, contains_unchecked))
            finally:
                model.blockSignals(False)

    def on_itemChanged(self, item):
        """
        This slot is called when some data changes in one of the
        TreeView. For us, since rows are read only, it is only
        triggered when a checkbox is checked/unchecked
        options
        @param item: item is the modified element. It can be a Shape, a Layer or an Entity
        """
        if item.column() == PATH_OPTIMISATION_COL:
            # User has clicked on the Path Optimisation (TSP) checkbox => update
            # the corresponding data.
            item_model_index = item.index().sibling(item.row(), 0)  # get the first column of the selected row, since it's the only one that contains data
            first_col_item = item_model_index.model().itemFromIndex(item_model_index)
            if isValid(first_col_item.data(SHAPE_OBJECT)):
                # Shape row: if the clicked row belongs to a multi-row
                # selection, the new state is applied to ALL selected shapes -
                # a click must not change only one row of the selection (this
                # also keeps an already enabled shape enabled when it is part
                # of a mixed multi-selection).
                checked = (item.checkState() != QtCore.Qt.CheckState.Unchecked)
                affected_items = self._pathOptimisationItemsForChange(item)
                model = item.model()
                model.blockSignals(True)  # avoid re-entrant itemChanged signals
                try:
                    for affected_item in affected_items:
                        affected_item.setCheckState(item.checkState())
                finally:
                    model.blockSignals(False)
                for affected_item in affected_items:
                    idx = affected_item.index().sibling(affected_item.row(), 0)
                    shapeobj = toPyObject(
                        model.itemFromIndex(idx).data(SHAPE_OBJECT)).shapeobj
                    shapeobj.setToolPathOptimized(checked)
                # keep the layer/entity row aggregation in sync
                for affected_item in affected_items:
                    self._updatePathOptimisationParentState(affected_item)
            elif isValid(first_col_item.data(LAYER_OBJECT)):
                # Layer row: apply ONE explicit target state to every shape
                # child (never invert each child individually). The layer
                # checkbox itself stays binary.
                checked = (item.checkState() != QtCore.Qt.CheckState.Unchecked)
                model = item.model()
                model.blockSignals(True)
                try:
                    for affected_item in self._pathOptimisationChildItems(
                            model, item.index().sibling(item.row(), 0)):
                        affected_item.setCheckState(
                            QtCore.Qt.CheckState.Checked if checked
                            else QtCore.Qt.CheckState.Unchecked)
                        idx = affected_item.index().sibling(affected_item.row(), 0)
                        shapeobj = toPyObject(
                            model.itemFromIndex(idx).data(SHAPE_OBJECT)).shapeobj
                        shapeobj.setToolPathOptimized(checked)
                finally:
                    model.blockSignals(False)

        elif isValid(item.data(SHAPE_OBJECT)) or isValid(item.data(CUSTOM_GCODE_OBJECT)):
            self.updateCheckboxOfItem(item, item.checkState())
            if self.auto_update_export_order:
                # update export order and thus export drawing
                self.prepareExportOrderUpdate()

        elif isValid(item.data(LAYER_OBJECT)):
            # Checkbox concerns a Layer object => check/uncheck each sub-items (shapes)
            self.traverseChildrenAndEnableDisable(self.layer_item_model, item.index(), item.checkState())
            if self.auto_update_export_order:
                self.prepareExportOrderUpdate()

        elif isValid(item.data(ENTITY_OBJECT)):
            # Checkbox concerns an Entity object => check/uncheck each sub-items (shapes and/or other entities)
            self.traverseChildrenAndEnableDisable(self.entity_item_model, item.index(), item.checkState())
            if self.auto_update_export_order:
                self.prepareExportOrderUpdate()

        g.window.canvas_scene.update()

    def updateCheckboxOfItem(self, item, check):
        """
        This function is used to effectively update the state of a
        checkbox and enable / disable texts when item is a shape
        @param item: item is the modified element. It can be a Shape, a Layer or an Entity
        @param check: the check state
        """
        item.model().blockSignals(True)  # Avoid unnecessary signal loops (we don't want the treeView to emit itemChanged signal)
        item.setCheckState(check)
        item.model().blockSignals(False)

        if isValid(item.data(SHAPE_OBJECT)):
            # Checkbox concerns a shape object
            real_item = toPyObject(item.data(SHAPE_OBJECT)).shapeobj
            self.setShapeDisabled(
                real_item, not check == QtCore.Qt.CheckState.Checked)

            # Update the other TreeViews
            item_index = self.findEntityItemIndexFromShape(real_item)
            if item_index:
                if item.model() == self.layer_item_model:
                    self.entity_item_model.blockSignals(True)  # Avoid unnecessary signal loops (we don't want the treeView to emit itemChanged signal)
                    item_other_tree = self.entity_item_model.itemFromIndex(item_index)
                    item_other_tree.setCheckState(check)
                    self.enableDisableTreeRow(item_other_tree, check)
                    self.entity_item_model.blockSignals(False)
                self.traverseParentsAndUpdateEnableDisable(self.entity_item_model, item_index)  # Update parents checkboxes

            item_index = self.findLayerItemIndexFromShape(real_item)
            if item_index:
                if item.model() == self.entity_item_model:
                    self.layer_item_model.blockSignals(True)  # Avoid unnecessary signal loops (we don't want the treeView to emit itemChanged signal)
                    item_other_tree = self.layer_item_model.itemFromIndex(item_index)
                    item_other_tree.setCheckState(check)
                    self.enableDisableTreeRow(item_other_tree, check)
                    self.layer_item_model.blockSignals(False)
                self.traverseParentsAndUpdateEnableDisable(self.layer_item_model, item_index)  # Update parents checkboxes

        if isValid(item.data(CUSTOM_GCODE_OBJECT)):
            # Checkbox concerns a custom gcode object
            real_item = toPyObject(item.data(CUSTOM_GCODE_OBJECT))
            self.setShapeDisabled(real_item, not check == QtCore.Qt.CheckState.Checked)
            self.traverseParentsAndUpdateEnableDisable(self.layer_item_model, item.index())  # Update parents checkboxes

        self.enableDisableTreeRow(item, check)

    def enableDisableTreeRow(self, item, check):
        """
        Enable / disable all the columns from a row, except the first
        one (because the first column contains the checkbox that must
        stay enabled in order to be clickable)
        @param item: item is the modified element.
                     It can be a Shape, a Layer or an Entity
        """
        if item.model() == self.layer_item_model:
            current_tree_view = self.ui.layersShapesTreeView
        else:
            current_tree_view = self.ui.entitiesTreeView

        item.model().blockSignals(True)
        if not item.parent():
            row_item = item.model().invisibleRootItem()  # parent is 0, so we need to get the root item of the tree as parent
            i = item.columnCount()
        else:
            row_item = item.parent()  # we are on one of the column of the row => take the parent, so that we get the complete row
            i = row_item.columnCount()
        row = item.row()
        while i > 1:
            i -= 1
            column_item = row_item.child(row, i)
            if column_item:
                column_item.setEnabled(False if check == QtCore.Qt.CheckState.Unchecked else True)
                current_tree_view.update(column_item.index())
        item.model().blockSignals(False)

        # Update the display (refresh the treeView for the given item)
        current_tree_view.update(item.index())


    def removeCustomGCodeSelected(self):
        """
        Don't concat this function with removeCustomGCode()!
        (since the action that triggers "removeCustomGCode" sends a parameter, the "shape_item_index" is never set to None otherwise...)
        """
        self.removeCustomGCode(None)

    def removeCustomGCode(self, shape_item_index = None):
        """
        Remove a custom GCode object from the treeView, just after the
        current item. Custom GCode are defined into the config file
        """
        logger.debug('Removing custom GCode...')
        current_item_index = shape_item_index
        if current_item_index is None:
            # No parameter passed => we use current item
            current_item_index = self.ui.layersShapesTreeView.currentIndex()

        if isValid(current_item_index):
            remove_row = current_item_index.row()

            # get the first column of the selected row, since it's the only one that contains data
            item_model_index = current_item_index.sibling(remove_row, 0)
            first_col_item = item_model_index.model().itemFromIndex(item_model_index)
            if isValid(first_col_item.data(CUSTOM_GCODE_OBJECT)):
                # Item is a Custom GCode, so we can remove it
                real_item = toPyObject(first_col_item.data(CUSTOM_GCODE_OBJECT))
                real_item.parentLayer.shapes.remove(real_item)

                first_col_item.parent().removeRow(remove_row)

            else:
                logger.warning(self.tr('Only Custom GCode items are removable!'))

    def addCustomGCodeAfter(self, action_name):
        """
        Add a custom GCode object into the treeView, just after the
        current item. Custom GCode are defined into the config file
        @param action_name: the name of the custom GCode to be inserted.
                            This name must match one of the subsection names
                            of [Custom_Actions] from the config file.
        """
        logger.debug('Adding custom GCode "%s"' % action_name)

        g_code = "(No custom GCode defined)"
        if action_name and len(action_name) > 0:
            g_code = g.config.vars.Custom_Actions[str(action_name)].gcode

        current_item_index = self.ui.layersShapesTreeView.currentIndex()
        if isValid(current_item_index):
            push_row = current_item_index.row() + 1  # insert after the current row
            current_item = current_item_index.model().itemFromIndex(current_item_index)
            current_item_parent = current_item.parent()

            if not current_item_parent:
                # parent is 0, so we are probably on a layer
                # get the first column of the selected row, since it's the only one that contains data
                current_item_parent_index = current_item_index.sibling(current_item_index.row(), 0)
                current_item_parent = current_item_parent_index.model().itemFromIndex(current_item_parent_index)
                push_row = 0  # insert before any shape

            if isValid(current_item_parent.data(LAYER_OBJECT)):
                real_item_parent = toPyObject(current_item_parent.data(LAYER_OBJECT))

                # creates a new CustomGCode instance
                custom_gcode = CustomGCode(action_name, g.window.newNumber, g_code, real_item_parent)
                g.window.newNumber += 1

                # insert this new item at the end of the physical list
                real_item_parent.shapes.append(custom_gcode)

                self.AddCustomGCodeRowLayer(custom_gcode, current_item_parent, push_row)
                self.ui.layersShapesTreeView.setCurrentIndex(current_item.index())

    def prepareExportOrderUpdate(self):
        """
        If the live update of export route is enabled, this function is
        called each time the shape order changes. It aims to update the drawing.
        """
        if self.auto_update_export_order:
            # Update the exported shapes
            self.updateExportOrder()

            # Emit the signal "exportOrderUpdated", so that the main can update tool path if he wants
            g.window.updateExportRoute()

    def setLiveUpdateExportRoute(self, live_update):
        """
        Set or unset the live update of export route.
        """
        self.auto_update_export_order = live_update

        if self.auto_update_export_order:
            self.prepareExportOrderUpdate()
