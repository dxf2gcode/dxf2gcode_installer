#!/usr/bin/env python3
# -*- coding: utf-8 -*-

############################################################################
#
#   Copyright (C) 2010-2016
#    Christian Kohlöffel
#    Jean-Paul Schouwstra
#
#   German translation & Python 3.10+ compatibility by Daniel Luginbühl
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

import argparse
import logging
import os
import subprocess
import sys
import tempfile
from math import degrees, radians

import dxf2gcode.domain.constants as c
import dxf2gcode.bootstrap.runtime_state as g
from dxf2gcode.domain.project.layercontent import Layers, Shapes
from dxf2gcode.domain.geometry.point import Point
from dxf2gcode.domain.project.project import Project
from dxf2gcode.bootstrap.composition import create_application_context
from dxf2gcode.application.drawings import BuildDrawingModel
from dxf2gcode.application.importing import ImportDrawing
from dxf2gcode.application.exporting import ExportToolpath
from dxf2gcode.application.projects import LoadProject, SaveProject
from dxf2gcode.application.optimization.routes import OptimizeRoutes
from dxf2gcode.application.optimization.tsp import TspOptimization
from dxf2gcode.application.shapes import AutomaticCutterCompensation
from dxf2gcode.adapters.dxf.reader import DxfReaderAdapter
from dxf2gcode.adapters.config.runtime_config import (MyConfig, active_config_profile_suffix,
                                      available_config_profiles,
                                      config_profile_folder, store_config_profile,
                                      stored_config_profile,
                                      validate_config_profile_suffix)
from dxf2gcode.application.text_helpers import qstr_encode, str_decode, str_encode
from dxf2gcode.bootstrap.logging import LoggerClass
from dxf2gcode.presentation.qt.aboutdialog import AboutDialog
from dxf2gcode.presentation.qt.versioninfo import version_details_html
from dxf2gcode.presentation.qt.configwindow import ConfigWindow
from dxf2gcode.presentation.qt.popupdialog import PopUpDialog
from dxf2gcode.presentation.qt.treehandling import TreeHandler
from dxf2gcode.adapters.postprocessor.postprocessor import MyPostProcessor
from dxf2gcode.adapters.postprocessor.postprocessorconfig import MyPostProConfig

from dxf2gcode.presentation.qt.qt_compat.QtWidgets import QMainWindow, QGraphicsView, QFileDialog, QApplication, QMenu, QMessageBox
from dxf2gcode.presentation.qt.qt_compat.QtGui import QActionGroup
from dxf2gcode.presentation.qt.qt_compat.QtGui import QSurfaceFormat
from dxf2gcode.presentation.qt.qt_compat import QtCore
from dxf2gcode.presentation.qt.qt_compat import PYQT_VERSION

logger = logging.getLogger()

g.folder = c.DEFAULT_CONFIG_FOLDER


def _log_import_filters(model):
    if model.excluded_layers:
        message = QtCore.QCoreApplication.translate(
            "ImportFilters", "Layers excluded from import: %s")
        logger.info(message, ", ".join(model.excluded_layers))


def _log_import_diagnostics(diagnostics):
    """Send import findings to the CLI logger, which replaces GUI dialogs."""
    for diagnostic in diagnostics:
        log = getattr(logger, diagnostic.severity, logger.warning)
        log("%s: %s", diagnostic.title, diagnostic.message)


def _run_headless_dxf_export(filename, output_filename, postprocessor_name,
                             optimize):
    """Run the CLI workflow without constructing a MainWindow."""
    from dxf2gcode.application.cli_export import ExportDrawing
    from dxf2gcode.domain.project.shape import Shape as DomainShape

    postprocessor = MyPostProcessor(create_config_window=False)
    if postprocessor.version_mismatch:
        logger.error(postprocessor.version_mismatch)
        return 2

    postprocessor_index = 0
    if postprocessor_name:
        for index, (name, extension) in enumerate(zip(
                postprocessor.output_text, postprocessor.output_format)):
            if postprocessor_name in (name, "%s (*%s)" % (name, extension)):
                postprocessor_index = index
                break
    extension = postprocessor.output_format[postprocessor_index]
    if (output_filename and
            os.path.splitext(output_filename)[1].lower() != extension.lower()):
        output_filename += extension

    conversion_dir = None
    original_filename = filename
    source_filename = filename
    extension_in = os.path.splitext(filename)[1].lower()
    if extension_in in ('.ps', '.pdf'):
        conversion_dir = tempfile.TemporaryDirectory(prefix='d2g_convert_')
        if extension_in == '.pdf':
            ps_filename = os.path.join(conversion_dir.name, 'input.ps')
            options = list(g.config.vars.Filters['pdftops_opt'])
            if options == ['']:
                options = []
            command = ([str(g.config.vars.Filters['pdftops_cmd'])] +
                       options +
                       [os.path.normcase(filename),
                        os.path.normcase(ps_filename)])
            logger.debug(command)
            try:
                result = subprocess.call(command)
            except OSError as error:
                logger.error("pdftops could not be started: %s", error)
                conversion_dir.cleanup()
                return 2
            if result:
                logger.error("pdftops returned error code %s", result)
                conversion_dir.cleanup()
                return 2
            source_filename = ps_filename

        dxf_filename = os.path.join(conversion_dir.name, 'input.dxf')
        options = list(g.config.vars.Filters['pstoedit_opt'])
        if options == ['']:
            options = []
        command = ([str(g.config.vars.Filters['pstoedit_cmd'])] + options +
                   [os.path.normcase(source_filename),
                    os.path.normcase(dxf_filename)])
        logger.debug(command)
        try:
            result = subprocess.call(command)
        except OSError as error:
            logger.error("pstoedit could not be started: %s", error)
            conversion_dir.cleanup()
            return 2
        if result:
            logger.error("pstoedit returned error code %s", result)
            conversion_dir.cleanup()
            return 2
        filename = dxf_filename

    import_drawing = ImportDrawing(DxfReaderAdapter(g.config))

    def build_model(drawing):
        return BuildDrawingModel(
            drawing=drawing,
            config=g.config,
            shape_factory=DomainShape,
            split_line_segments=g.config.vars.General['split_line_segments'],
            transform={
                "scale": g.config.vars.Plane_Coordinates['std_scale'],
            },
        ).execute()

    g.window = None
    g.quiet = True
    try:
        _model, diagnostics = ExportDrawing(
            import_drawing=import_drawing,
            build_model=build_model,
            postprocessor=postprocessor,
            config=g.config,
            optimizer_factory=TspOptimization,
        ).execute(original_filename, output_filename, optimize=optimize,
                  postprocessor_index=postprocessor_index,
                  import_filename=filename if conversion_dir is not None
                  else None)
        _log_import_diagnostics(diagnostics)
        _log_import_filters(_model)
        return 0
    except Exception as error:
        logger.error("Drawing export failed: %s", error)
        return 2
    finally:
        if conversion_dir is not None:
            conversion_dir.cleanup()


def _run_headless_project_export(filename, output_filename,
                                 postprocessor_name, optimize):
    """Load a .d2g project and export it without creating a MainWindow."""
    from dxf2gcode.application.cli_export import ExportProject

    postprocessor = MyPostProcessor(create_config_window=False)
    if postprocessor.version_mismatch:
        logger.error(postprocessor.version_mismatch)
        return 2

    postprocessor_index = 0
    if postprocessor_name:
        for index, (name, extension) in enumerate(zip(
                postprocessor.output_text, postprocessor.output_format)):
            if postprocessor_name in (name, "%s (*%s)" % (name, extension)):
                postprocessor_index = index
                break
    extension = postprocessor.output_format[postprocessor_index]
    if (output_filename and
            os.path.splitext(output_filename)[1].lower() != extension.lower()):
        output_filename += extension

    g.window = None
    g.quiet = True
    try:
        _model, diagnostics = ExportProject(
            project_repository=create_application_context(
                config=g.config, logger=logger, quiet=True
            ).project_repository,
            config=g.config,
            postprocessor=postprocessor,
            optimizer_factory=TspOptimization,
        ).execute(filename, output_filename, optimize=optimize,
                  postprocessor_index=postprocessor_index)
        _log_import_diagnostics(diagnostics)
        _log_import_filters(_model)
    except Exception as error:
        logger.error("Project export failed: %s", error)
        return 2
    return 0


class MainWindow(QMainWindow):

    """
    Main Class
    """

    # Define a QT signal that is emitted when the configuration changes.
    # Connect to this signal if you need to know when the configuration has
    # changed.
    configuration_changed = QtCore.pyqtSignal()

    def __init__(self, app, application_context=None):
        """
        Initialization of the Main window. This is directly called after the
        Logger has been initialized. The Function loads the GUI, creates the
        used Classes and connects the actions to the GUI.
        """
        QMainWindow.__init__(self)

        self.application_context = application_context or create_application_context(
            config=g.config, logger=logger, quiet=g.quiet)

        # Build the configuration window
        self.config_window = ConfigWindow(g.config.makeConfigWidgets(),
                                          g.config.var_dict,
                                          g.config.var_dict.configspec,
                                          self)
        self.config_window.finished.connect(self.updateConfiguration)

        self.app = app
        self.settings = QtCore.QSettings("dxf2gcode", "dxf2gcode")

        self.ui = Ui_MainWindow()

        self.ui.setupUi(self)
        self.showMaximized()

        self.canvas = self.ui.canvas
        if g.config.mode3d:
            self.canvas_scene = self.canvas
        else:
            self.canvas_scene = None

        self.TreeHandler = TreeHandler(self.ui)
        self.configuration_changed.connect(self.TreeHandler.updateConfiguration)
        # The canvas overlays (e.g. the scale bar) depend on the configuration
        # and on the measurement units.
        self.configuration_changed.connect(self.updateCanvasOverlay)

        if sys.version_info[0] == 2:
            error_message = QMessageBox(QMessageBox.Critical, self.tr('ERROR'), self.tr("Python version 2 is not supported, please use it with python version 3."))
            sys.exit(error_message.exec())

        # Load the post-processor configuration and build the post-processor configuration window
        self.MyPostProcessor = MyPostProcessor()
        # If string version_mismatch isn't empty, we popup an error and exit
        if self.MyPostProcessor.version_mismatch:
            error_message = QMessageBox(QMessageBox.Critical, self.tr('Configuration error'), self.MyPostProcessor.version_mismatch)
            sys.exit(error_message.exec())

        self.d2g = Project(self)
        self.project_repository = self.application_context.project_repository

        self.createActions()
        self.connectToolbarToConfig()

        self.filename = ""

        self.valuesDXF = None
        self.shapes = Shapes([])
        self.entityRoot = None
        self.layerContents = Layers([])
        self.newNumber = 1

        self.cont_dx = 0.0
        self.cont_dy = 0.0
        self.cont_rotate = 0.0
        self.cont_scale = g.config.vars.Plane_Coordinates['std_scale']
        self.cont_mirrorx = False
        self.cont_mirrory = False

        self.restoreWindowState()

    def tr(self, string_to_translate):
        """
        Translate a string using the QCoreApplication translation framework
        @param: string_to_translate: a unicode string
        @return: the translated unicode string if it was possible to translate
        """
        return str(QtCore.QCoreApplication.translate('MainWindow',
                                                           string_to_translate))

    def createActions(self):
        """
        Create the actions of the main toolbar.
        @purpose: Links the callbacks to the actions in the menu
        """

        # File
        self.ui.actionOpen.triggered.connect(self.open)
        self.ui.actionReload.triggered.connect(self.reload)
        self.ui.actionSaveProjectAs.triggered.connect(self.saveProject)
        self.ui.actionClose.triggered.connect(self.close)

        # Export
        self.ui.actionOptimizePaths.triggered.connect(self.optimizeTSP)
        self.ui.actionExportShapes.triggered.connect(self.exportShapes)
        self.ui.actionOptimizeAndExportShapes.triggered.connect(self.optimizeAndExportShapes)

        # View
        self.ui.actionShowPathDirections.triggered.connect(self.setShowPathDirections)
        # We need toggled (and not triggered), otherwise the signal is not
        # emitted when state is changed programmatically
        self.ui.actionShowDisabledPaths.toggled.connect(self.setShowDisabledPaths)
        self.ui.actionLiveUpdateExportRoute.toggled.connect(self.liveUpdateExportRoute)
        self.ui.actionDeleteG0Paths.triggered.connect(self.deleteG0Paths)
        self.ui.actionAutoscale.triggered.connect(self.canvas.autoscale)
        if g.config.mode3d:
            self.ui.actionTopView.triggered.connect(self.canvas.topView)
            self.ui.actionIsometricView.triggered.connect(self.canvas.isometricView)

        # Options
        self.ui.actionConfiguration.triggered.connect(self.config_window.show)
        self.ui.actionConfigurationPostprocessor.triggered.connect(self.MyPostProcessor.config_postpro_window.show)
        self.createConfigProfileMenu()
        self.ui.actionTolerances.triggered.connect(self.setTolerances)
        self.ui.actionRotateAll.triggered.connect(self.rotateAll)
        self.ui.actionScaleAll.triggered.connect(self.scaleAll)
        self.ui.actionMirrorAll.triggered.connect(self.MirrorAll)
        self.ui.actionMoveWorkpieceZero.triggered.connect(self.moveWorkpieceZero)
        self.ui.actionSplitLineSegments.toggled.connect(self.d2g.small_reload)
        self.ui.actionAutomaticCutterCompensation.toggled.connect(self.d2g.small_reload)
        self.ui.actionMilling.triggered.connect(self.setMachineTypeToMilling)
        self.ui.actionDragKnife.triggered.connect(self.setMachineTypeToDragKnife)
        self.ui.actionLathe.triggered.connect(self.setMachineTypeToLathe)
        self.ui.actionMillimeters.triggered.connect(self.setMeasurementUnitsToMillimeters)
        self.ui.actionInches.triggered.connect(self.setMeasurementUnitsToInches)

        # Help
        self.ui.actionAbout.triggered.connect(self.about)

    def createConfigProfileMenu(self):
        """
        Add the configuration profile selector to the existing Options menu.
        The submenu lists every detected profile (based on the real
        configuration folder of this platform) and allows to create a new
        profile. Switching a profile requires a restart: the choice is
        remembered and applied on the next program start.
        """
        self.menu_config_profile = QMenu(self.tr("Configuration profile"), self.ui.menuOptions)
        self.menu_config_profile.setObjectName("menuConfigProfile")
        self.config_profile_group = QActionGroup(self)
        self.config_profile_group.setExclusive(True)
        # Insert at the top of the Options menu, right in front of the
        # configuration entries it belongs to.
        self.ui.menuOptions.insertMenu(self.ui.actionConfiguration, self.menu_config_profile)
        self.updateConfigProfileMenu()

    def updateConfigProfileMenu(self):
        """
        Rebuild the profile submenu from the profiles found on disk. The active
        profile is checked, a profile that was selected but needs a restart to
        become active is marked accordingly.
        """
        self.menu_config_profile.clear()

        active = active_config_profile_suffix()
        pending = stored_config_profile()
        profiles = available_config_profiles()

        suffixes = [''] + [suffix for suffix in profiles if suffix]
        for suffix in suffixes:
            label = suffix if suffix else self.tr("default")
            if suffix == active:
                label = label + " " + self.tr("(active)")
            elif pending is not None and suffix == pending and pending != active:
                label = label + " " + self.tr("(restart to apply)")

            action = self.menu_config_profile.addAction(label)
            action.setCheckable(True)
            action.setChecked(suffix == active)
            action.triggered.connect(lambda checked=False, s=suffix: self.selectConfigProfile(s))
            self.config_profile_group.addAction(action)

        self.menu_config_profile.addSeparator()
        new_profile_action = self.menu_config_profile.addAction(self.tr("New profile..."))
        new_profile_action.triggered.connect(self.createConfigProfile)

    def selectConfigProfile(self, suffix):
        """
        Remember the requested profile and ask the user to restart. A safe
        switch at runtime is deliberately not performed: the configuration,
        the tool table and the post-processor configuration are all loaded
        once at startup, so only a restart guarantees a consistent profile.
        @param suffix: the suffix of the requested profile ('' for default)
        """
        if suffix == active_config_profile_suffix():
            return

        if not self.handleUnsavedConfigChanges():
            self.updateConfigProfileMenu()
            return

        store_config_profile(suffix)
        self.updateConfigProfileMenu()

        name = suffix if suffix else self.tr("default")
        QMessageBox.information(self, self.tr("Configuration profile"),
                                self.tr('The configuration profile "{0}" will be used '
                                        'after DXF2GCODE has been restarted.').format(name))

    def handleUnsavedConfigChanges(self):
        """
        Make sure no pending modifications are lost when the profile changes.
        Uses the existing edit state of the configuration windows.
        @return: True when the profile switch may continue, False when the user
                 cancelled or the changes could not be saved.
        """
        windows = [self.config_window, self.MyPostProcessor.config_postpro_window]
        windows = [window for window in windows if window.isEditing()]
        if not windows:
            return True

        answer = QMessageBox.question(self, self.tr("Unsaved changes"),
                                      self.tr("The configuration contains unsaved changes.\n"
                                              "Do you want to save them before switching the profile?"),
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Save:
            return False

        for window in windows:
            window.applyChanges()
            if window.isEditing():
                # The changes could not be saved (eg invalid values), so the
                # profile must not be switched.
                return False
        return True

    def createConfigProfile(self):
        """
        Create a new configuration profile. The new profile starts with the
        application's default values (it is not a copy of the current profile),
        matching how a new post-processor configuration is created.
        """
        title = self.tr('Create a configuration profile')
        label = [self.tr("Enter a name for the new profile:")]
        value = [""]
        wtype = ["lineEdit"]
        name_dialog = PopUpDialog(title, label, value, wtype)

        if name_dialog.result is None:
            return

        suffix = str(name_dialog.result[0]).strip()
        valid, message = validate_config_profile_suffix(suffix)
        if not valid:
            QMessageBox.warning(self, title, message)
            return

        if suffix in available_config_profiles():
            QMessageBox.warning(self, title,
                                self.tr('A configuration profile named "{0}" already exists.').format(suffix))
            return

        if not self.initializeConfigProfile(suffix):
            QMessageBox.warning(self, title,
                                self.tr('The configuration profile "{0}" could not be created.').format(suffix))
            return

        self.selectConfigProfile(suffix)

    def initializeConfigProfile(self, suffix):
        """
        Create the folder of a new profile and initialize it with default
        configuration files, reusing the regular configuration management.
        @param suffix: the suffix of the new profile
        @return: True on success
        """
        folder = config_profile_folder(suffix)
        if os.path.exists(folder):
            # The folder exists already, so it is not a new profile. Its
            # configuration files are created on first use.
            return True

        previous_folder = g.folder
        try:
            g.folder = folder
            # Reuses the existing configuration classes: they create the
            # profile folder plus a config.cfg / postpro_config.cfg with the
            # application's default values.
            MyConfig()
            MyPostProConfig().create_default_config()
            return True
        except Exception as inst:
            logger.error(self.tr("Could not initialize configuration profile '%s': %s") % (suffix, inst))
            return False
        finally:
            g.folder = previous_folder

    def connectToolbarToConfig(self, project=False, block_signals=True):
        # View
        if not project:
            self.ui.actionShowDisabledPaths.blockSignals(block_signals)  # Don't emit any signal when changing state of the menu entries
            self.ui.actionShowDisabledPaths.setChecked(g.config.vars.General['show_disabled_paths'])
            self.ui.actionShowDisabledPaths.blockSignals(False)
            self.ui.actionLiveUpdateExportRoute.blockSignals(block_signals)
            self.ui.actionLiveUpdateExportRoute.setChecked(g.config.vars.General['live_update_export_route'])
            self.ui.actionLiveUpdateExportRoute.blockSignals(False)

        # Options
        self.ui.actionSplitLineSegments.blockSignals(block_signals)
        self.ui.actionSplitLineSegments.setChecked(g.config.vars.General['split_line_segments'])
        self.ui.actionSplitLineSegments.blockSignals(False)
        self.ui.actionAutomaticCutterCompensation.blockSignals(block_signals)
        self.ui.actionAutomaticCutterCompensation.setChecked(g.config.vars.General['automatic_cutter_compensation'])
        self.ui.actionAutomaticCutterCompensation.blockSignals(False)
        self.updateMachineType()

    def keyPressEvent(self, event):
        """
        Rewritten KeyPressEvent to get other behavior while Shift is pressed.
        @purpose: Changes to ScrollHandDrag while Control pressed
        @param event:    Event Parameters passed to function
        """
        if event.isAutoRepeat():
            return
        if g.config.mode3d:
            self.canvas.updateModifiers(event)
        elif event.key() == QtCore.Qt.Key.Key_Control:
            self.canvas.isMultiSelect = True
        elif event.key() == QtCore.Qt.Key.Key_Shift:
            self.canvas.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

    def keyReleaseEvent(self, event):
        """
        Rewritten KeyReleaseEvent to get other behavior while Shift is pressed.
        @purpose: Changes to RubberBandDrag while Control released
        @param event:    Event Parameters passed to function
        """
        if g.config.mode3d:
            self.canvas.updateModifiers(event)
        elif event.key() == QtCore.Qt.Key.Key_Control:
            self.canvas.isMultiSelect = False
        elif event.key() == QtCore.Qt.Key.Key_Shift:
            self.canvas.setDragMode(QGraphicsView.DragMode.NoDrag)

    def enableToolbarButtons(self, status=True):
        # File
        self.ui.actionReload.setEnabled(status)
        self.ui.actionSaveProjectAs.setEnabled(status)

        # Export
        self.ui.actionOptimizePaths.setEnabled(status)
        self.ui.actionExportShapes.setEnabled(status)
        self.ui.actionOptimizeAndExportShapes.setEnabled(status)

        # View
        self.ui.actionShowPathDirections.setEnabled(status)
        self.ui.actionShowDisabledPaths.setEnabled(status)
        self.ui.actionLiveUpdateExportRoute.setEnabled(status)
        self.ui.actionAutoscale.setEnabled(status)
        if g.config.mode3d:
            self.ui.actionTopView.setEnabled(status)
            self.ui.actionIsometricView.setEnabled(status)

        # Options
        self.ui.actionTolerances.setEnabled(status)
        self.ui.actionRotateAll.setEnabled(status)
        self.ui.actionScaleAll.setEnabled(status)
        self.ui.actionMirrorAll.setEnabled(status)
        self.ui.actionMoveWorkpieceZero.setEnabled(status)

    def deleteG0Paths(self):
        """
        Deletes the optimisation paths from the scene.
        """
        self.setCursor(QtCore.Qt.CursorShape.WaitCursor)
        self.app.processEvents()

        self.canvas_scene.delete_opt_paths()
        self.ui.actionDeleteG0Paths.setEnabled(False)
        self.canvas_scene.update()

        self.unsetCursor()

    def isToolpathError(self, message):
        """
        Check whether an error message belongs to the tool path (the lead in,
        the lead out or the overcut).

        @param message: the error message
        @return: True if the error belongs to the tool path
        """
        lowered = str(message).lower()
        return any(keyword in lowered for keyword in (
            "tool path", "lead out", "lead in", "overcut", "lead-in", "lead-out"))

    def showToolpathErrorMessages(self, errors):
        """
        Show the collected errors of the tool path (the lead in, the lead out
        or the overcut) in one message box.

        @param errors: the error messages
        """
        QMessageBox.critical(
            self, self.tr("Ungültige Werkzeugweg-Einstellungen"),
            "\n".join(str(error) for error in errors))

    def showToolpathError(self, message):
        """
        Show an error of the tool path (the lead in, the lead out or the
        overcut) in a message box.

        @param message: the error message
        """
        if not message:
            return
        self.showToolpathErrorMessages([str(message)])

    def exportShapes(self, status=False, saveas=None):
        """
        This function is called by the menu "Export/Export Shapes". It may open
        a Save Dialog if used without LinuxCNC integration. Otherwise it's
        possible to select multiple postprocessor files, which are located
        in the folder.
        """
        self.setCursor(QtCore.Qt.CursorShape.WaitCursor)
        self.app.processEvents()

        logger.debug(self.tr('Export the enabled shapes'))

        # Get the export order from the QTreeView
        self.TreeHandler.updateExportOrder()
        self.updateExportRoute()

        logger.debug(self.tr("Sorted layers:"))
        for i, layer in enumerate(self.layerContents.non_break_layer_iter()):
            logger.debug("LayerContents[%i] = %s" % (i, layer))

        if not g.config.vars.General['write_to_stdout']:

            # Get the name of the File to export
            if not saveas:
                MyFormats = ""
                for i in range(len(self.MyPostProcessor.output_format)):
                    name = "%s " % (self.MyPostProcessor.output_text[i])
                    format_ = "(*%s);;" % (self.MyPostProcessor.output_format[i])
                    MyFormats = MyFormats + name + format_
                filename = self.showSaveDialog(self.tr('Export to file'), MyFormats, g.config.vars.Paths['output_dir'])
                save_filename = qstr_encode(filename[0])
            else:
                filename = [None, options.post_pro]
                save_filename = saveas

            # If Cancel was pressed
            if not save_filename:
                self.unsetCursor()
                return

            # If automatic save paths is checked keep it up to date.
            if g.config.vars.Paths['autosave_path']:
                logger.debug("Save output_dir")
                g.config.var_dict["Paths"]["output_dir"]=os.path.dirname(save_filename)
                g.config.update_config()
                g.config.save_varspace()

            (beg, ende) = os.path.split(save_filename)
            (fileBaseName, fileExtension) = os.path.splitext(ende)

            pp_file_nr = 0
            for i in range(len(self.MyPostProcessor.output_format)):
                name = "%s " % (self.MyPostProcessor.output_text[i])
                format_ = "(*%s)" % (self.MyPostProcessor.output_format[i])
                MyFormats = name + format_
                if filename[1] == MyFormats:
                    pp_file_nr = i
            if fileExtension != self.MyPostProcessor.output_format[pp_file_nr]:
                if not QtCore.QFile.exists(save_filename):
                    save_filename += self.MyPostProcessor.output_format[pp_file_nr]

            logger.debug("File Ending => Postprocessor Nr: %i" % (pp_file_nr))
        else:
            save_filename = ""
            logger.debug("EMC Integration => Postprocessor Nr: %i" % (0))
            pp_file_nr = 0

        """
        Export will be performed according to LayerContents and their order
        is given in this variable too.
        """

        # Prepare if any exception happens during export
        #try:
        export_errors = ExportToolpath(self.MyPostProcessor).execute(
            self.filename, save_filename, self.layerContents, pp_file_nr)
        #except Exception as e:
        #    logger.error(self.tr('Error exporting shapes: %s') % str (e))

        # The errors of the export (e.g. an invalid lead in radius or an
        # invalid lead out / overcut geometry) are collected during the
        # export and shown at the end of it.
        if export_errors:
            toolpath_errors = [str(error) for error in export_errors
                                if self.isToolpathError(str(error))]
            if toolpath_errors:
                self.showToolpathErrorMessages(toolpath_errors)
            else:
                QMessageBox.warning(self, self.tr("Export errors"),
                                    "\n".join(export_errors))

        self.unsetCursor()

        if g.config.vars.General['write_to_stdout']:
            self.close()

    def optimizeAndExportShapes(self, saveas=None, post_pro=None):
        """
        Optimize the tool path, then export the shapes
        """
        self.optimizeTSP()
        self.exportShapes( saveas, post_pro)

    def updateExportRoute(self):
        """
        Update the drawing of the export route
        """
        self.canvas_scene.delete_opt_paths()

        self.canvas_scene.addexproutest()
        for layer in self.layerContents.non_break_layer_iter():
            if len(layer.exp_order) > 0:
                self.canvas_scene.addexproute(layer.exp_order, layer.nr)
        if len(self.canvas_scene.routearrows) > 0:
            self.ui.actionDeleteG0Paths.setEnabled(True)
            self.canvas_scene.addexprouteen()
        self.canvas_scene.update()

    def optimizeTSP(self):
        """
        Method is called to optimize the order of the shapes. This is performed
        by solving the TSP Problem.
        """
        self.setCursor(QtCore.Qt.CursorShape.WaitCursor)
        self.app.processEvents()

        logger.debug(self.tr('Optimize order of enabled shapes per layer'))
        self.canvas_scene.delete_opt_paths()

        # Get the export order from the QTreeView
        logger.debug(self.tr('Updating order according to TreeView'))
        self.TreeHandler.updateExportOrder()
        self.canvas_scene.addexproutest()

        x_st = g.config.vars.Plane_Coordinates['axis1_start_end']
        y_st = g.config.vars.Plane_Coordinates['axis2_start_end']

        def update_layer_route(layer_content):
            logger.debug(self.tr("New Export Order after TSP: %s")
                         % layer_content.exp_order)
            self.canvas_scene.addexproute(layer_content.exp_order,
                                          layer_content.nr)
            self.app.processEvents()

        OptimizeRoutes(
            optimizer_factory=TspOptimization,
            max_iterations=g.config.vars.Route_Optimisation['max_iterations'],
            start_point=Point(x_st, y_st),
            route_settings=g.config.vars.Route_Optimisation,
        ).execute(self.layerContents.non_break_layer_iter(), self.shapes,
                  after_layer=update_layer_route)

        if len(self.canvas_scene.routearrows) > 0:
            self.ui.actionDeleteG0Paths.setEnabled(True)
            self.canvas_scene.addexprouteen()

        # Update order in the treeView, according to path calculation done by the TSP
        self.TreeHandler.updateTreeViewOrder()
        self.canvas_scene.update()

        self.unsetCursor()

    def automaticCutterCompensation(self):
        enabled = (self.ui.actionAutomaticCutterCompensation.isEnabled() and
                   self.ui.actionAutomaticCutterCompensation.isChecked())
        changed_shapes = AutomaticCutterCompensation().execute(
            self.layerContents.non_break_layer_iter(), enabled,
            g.config.machine_type)
        for shape in changed_shapes:
            self.canvas_scene.repaint_shape(shape)
        self.TreeHandler.updateTreeViewOrder()
        self.canvas_scene.update()

    def showSaveDialog(self, title, MyFormats, save_to_folder):
        """
        This function is called by the menu "Export/Export Shapes" of the main toolbar.
        It creates the selection dialog for the exporter
        @return: Returns the filename of the selected file.
        """

        (beg, ende) = os.path.split(self.filename)
        (fileBaseName, fileExtension) = os.path.splitext(ende)

        default_name = os.path.join(save_to_folder, fileBaseName)
        logger.debug("default_name: %s", default_name)

        selected_filter = self.MyPostProcessor.output_format[0]
        filename = QFileDialog.getSaveFileName(self,
                                   title, default_name,
                                   MyFormats, selected_filter)


        logger.debug(filename)
        # If there is something to load then call the load function callback
        if filename:
            #filename = qstr_encode(filename)
            logger.info(self.tr("File: %s selected") % filename[0])
            logger.info(self.tr("Filter: %s selected") % filename[1])
            logger.info("<a href='%s'>%s</a>" % (filename[0], filename[0]))
            return filename
        else:
            return False

    def about(self):
        """
        This function is called by the menu "Help/About" of the main toolbar and
        creates the About Window
        """

        message = self.tr("<html>"
                          "<h2><center>You are using</center></h2>"
                          "<body bgcolor="
                          "<center><img src=':images/dxf2gcode_logo.png' border='1' color='white'></center></body>"
                          "<h2>Version:</h2>"
                          "<body>%s</body>"
                          "<h2>Where to get help:</h2>"
                          "For more information and updates, "
                          "please visit "
                          "<a href='http://sourceforge.net/projects/dxf2gcode/'>http://sourceforge.net/projects/dxf2gcode/</a><br>"
                          "For any questions on how to use dxf2gcode please use the "
                          "<a href='https://www.ltspiceusers.ch/forums/english-section.67/'>https://www.ltspiceusers.ch/forums/english-section.67/</a><br>"
                          "To log bugs, or request features please use the "
                          "<a href='http://sourceforge.net/p/dxf2gcode/tickets/'>issue tracking system</a><br>"
                          "<h2>License and copyright:</h2>"
                          "<body>This program is written in Python and is published under the "
                          "<a href='http://www.gnu.org/licenses/'>GNU GPLv3 license.</a><br>"
                          "</body></html>") % version_details_html()

        AboutDialog(title=self.tr("About DXF2GCODE"), message=message)

    def setShowPathDirections(self):
        """
        This function is called by the menu "Show all path directions" of the
        main and forwards the call to Canvas.setShow_path_direction()
        """
        flag = self.ui.actionShowPathDirections.isChecked()
        self.canvas.setShowPathDirections(flag)
        self.canvas_scene.update()

    def setShowDisabledPaths(self):
        """
        This function is called by the menu "Show disabled paths" of the
        main and forwards the call to Canvas.setShow_disabled_paths()
        """
        flag = self.ui.actionShowDisabledPaths.isChecked()
        self.canvas_scene.setShowDisabledPaths(flag)
        self.canvas_scene.update()

    def liveUpdateExportRoute(self):
        """
        This function is called by the menu "Live update tool path" of the
        main and forwards the call to TreeHandler.setUpdateExportRoute()
        """
        flag = self.ui.actionLiveUpdateExportRoute.isChecked()
        self.TreeHandler.setLiveUpdateExportRoute(flag)

    def setTolerances(self):
        title = self.tr('Contour tolerances')
        units = "in" if g.config.metric == 0 else "mm"
        label = [self.tr("Tolerance for common points [%s]:") % units,
                 self.tr("Tolerance for curve fitting [%s]:") % units]
        value = [g.config.point_tolerance,
                 g.config.fitting_tolerance]
        wtype = ["lineEdit", "lineEdit"]

        logger.debug(self.tr("set Tolerances"))
        SetTolDialog = PopUpDialog(title, label, value, wtype)

        if SetTolDialog.result is None:
            return

        g.config.point_tolerance = float(SetTolDialog.result[0])
        g.config.fitting_tolerance = float(SetTolDialog.result[1])

        self.d2g.reload()  # set tolerances requires a complete reload



    def MirrorAll(self):
        title = self.tr('Mirror all X / Y-Axis')
        label = [self.tr("Mirror all on X-Axis:"), self.tr("Mirror all on Y-Axis:")]
        value = [self.cont_mirrorx, self.cont_mirrory]
        wtype = ["checkBox","checkBox"]
        MirrorDialog = PopUpDialog(title, label, value, wtype)

        if MirrorDialog.result is None:
            return

        self.cont_mirrorx = MirrorDialog.result[0]
        self.cont_mirrory = MirrorDialog.result[1]

        self.entityRoot.mirrorx = self.cont_mirrorx
        self.entityRoot.mirrory = self.cont_mirrory

        self.d2g.small_reload()

    def scaleAll(self):
        title = self.tr('Scale Contour')
        label = [self.tr("Scale Contour by factor:")]
        value = [self.cont_scale]
        wtype = ["lineEdit"]
        ScaEntDialog = PopUpDialog(title, label, value, wtype)

        if ScaEntDialog.result is None:
            return

        self.cont_scale = float(ScaEntDialog.result[0])
        self.entityRoot.sca = self.cont_scale

        self.d2g.small_reload()

    def rotateAll(self):
        title = self.tr('Rotate Contour')
        # TODO should we support radians for drawing unit non metric?
        label = [self.tr("Rotate Contour by deg:")]
        value = [degrees(self.cont_rotate)]
        wtype = ["lineEdit"]
        RotEntDialog = PopUpDialog(title, label, value, wtype)

        if RotEntDialog.result is None:
            return

        self.cont_rotate = radians(float(RotEntDialog.result[0]))
        self.entityRoot.rot = self.cont_rotate

        self.d2g.small_reload()

    def moveWorkpieceZero(self):
        """
        This function is called when the Option=>Move WP Zero Menu is clicked.
        """
        title = self.tr('Workpiece zero offset')
        units = "[in]" if g.config.metric == 0 else "[mm]"
        label = [self.tr("Offset %s axis %s:") % (g.config.vars.Axis_letters['ax1_letter'], units),
                 self.tr("Offset %s axis %s:") % (g.config.vars.Axis_letters['ax2_letter'], units)]
        value = [self.cont_dx, self.cont_dy]
        wtype = ["lineEdit","lineEdit"]
        MoveWpzDialog = PopUpDialog(title, label, value, wtype, True)

        if MoveWpzDialog.result is None:
            return

        if MoveWpzDialog.result == 'Auto':
            minx = sys.float_info.max
            miny = sys.float_info.max
            for shape in self.shapes:
                if not shape.isDisabled():
                    minx = min(minx, shape.BB.Ps.x)
                    miny = min(miny, shape.BB.Ps.y)
            if not (minx == sys.float_info.max or miny == sys.float_info.max):
                self.cont_dx = self.entityRoot.p0.x - minx
                self.cont_dy = self.entityRoot.p0.y - miny
        else:
            self.cont_dx = float(MoveWpzDialog.result[0])
            self.cont_dy = float(MoveWpzDialog.result[1])

        if self.entityRoot.p0.x != self.cont_dx or self.entityRoot.p0.y != self.cont_dy:
            self.entityRoot.p0.x = self.cont_dx
            self.entityRoot.p0.y = self.cont_dy

            self.d2g.small_reload()
        else:
            logger.info(self.tr("No differences found. Ergo, workpiece zero is not moved"))

    def setMachineTypeToMilling(self):
        g.config.machine_type = 'milling'
        self.updateMachineType()
        self.d2g.small_reload()

    def setMachineTypeToDragKnife(self):
        g.config.machine_type = 'drag_knife'
        self.updateMachineType()
        self.d2g.small_reload()

    def setMachineTypeToLathe(self):
        g.config.machine_type = 'lathe'
        self.updateMachineType()
        self.d2g.small_reload()

    def updateMachineType(self):
        if g.config.machine_type == 'milling':
            self.ui.actionAutomaticCutterCompensation.setEnabled(True)
            self.ui.actionMilling.setChecked(True)
            self.ui.actionDragKnife.setChecked(False)
            self.ui.actionLathe.setChecked(False)
            self.ui.label_9.setText(self.tr("Z Infeed depth"))
        elif g.config.machine_type == 'lathe':
            self.ui.actionAutomaticCutterCompensation.setEnabled(False)
            self.ui.actionMilling.setChecked(False)
            self.ui.actionDragKnife.setChecked(False)
            self.ui.actionLathe.setChecked(True)
            self.ui.label_9.setText(self.tr("No Z-Axis for lathe"))
        elif g.config.machine_type == "drag_knife":
            self.ui.actionAutomaticCutterCompensation.setEnabled(False)
            self.ui.actionMilling.setChecked(False)
            self.ui.actionDragKnife.setChecked(True)
            self.ui.actionLathe.setChecked(False)
            self.ui.label_9.setText(self.tr("Z Drag depth"))

    def setMeasurementUnitsToMillimeters(self):
        self.setMeasurementUnits(1)

    def setMeasurementUnitsToInches(self):
        self.setMeasurementUnits(0)

    def setMeasurementUnits(self, metric, refresh_ui=False):
        """
        Change the measurement units used in DXF file.
        Helps if dxf2gcode was unable to detect the correct units.
        """

        self.ui.menu_Measurement_units.setEnabled(True)
        self.ui.actionMillimeters.setChecked(metric == 1)
        self.ui.actionInches.setChecked(metric == 0)

        if (g.config.metric != metric) or refresh_ui:
            if metric == 0:
                logger.info(self.tr("Drawing units: inches"))
                distance = self.tr("[in]")
                speed = self.tr("[IPM]")
            else:
                logger.info(self.tr("Drawing units: millimeters"))
                distance = self.tr("[mm]")
                speed = self.tr("[mm/min]")
            self.ui.unitLabel_3.setText(distance)
            self.ui.unitLabel_4.setText(distance)
            self.ui.unitLabel_5.setText(distance)
            self.ui.unitLabel_6.setText(distance)
            self.ui.unitLabel_7.setText(distance)
            self.ui.unitLabel_8.setText(speed)
            self.ui.unitLabel_9.setText(speed)

        if g.config.metric != metric:
            for layerContent in self.layerContents:
                layerContent.changeMeasuringUnits(g.config.metric, metric)
            g.config.metric = metric
            g.config.update_tool_values()
            self.configuration_changed.emit()
            self.TreeHandler.updateToolParameters()

    def open(self):
        """
        This function is called by the menu "File/Load File" of the main toolbar.
        It creates the file selection dialog and calls the load function to
        load the selected file.
        """

        self.OpenFileDialog(self.tr("Open file"))

        # If there is something to load then call the load function callback
        if self.filename:
            self.cont_dx = 0.0
            self.cont_dy = 0.0
            self.cont_rotate = 0.0
            self.cont_scale =  g.config.vars.Plane_Coordinates['std_scale']
            self.cont_mirrorx = False
            self.cont_mirrory = False

            self.load()

    def OpenFileDialog(self, title):
        self.filename, _ = QFileDialog. getOpenFileName(self,
                                           title,
                                           g.config.vars.Paths['import_dir'],
                                           self.tr("All supported files (*.dxf *.DXF *.ps *.PS *.pdf *.PDF *%s);;"
                                                   "DXF files (*.dxf *.DXF);;"
                                                   "PS files (*.ps *.PS);;"
                                                   "PDF files (*.pdf *.PDF);;"
                                                   "Project files (*%s);;"
                                                   "All types (*.*)") % (c.PROJECT_EXTENSION, c.PROJECT_EXTENSION))


        # If there is something to load then call the load function callback
        if not(self.filename):
            return

        # If automatic save paths is checked keep it up to date.
        if g.config.vars.Paths['autosave_path']:
            logger.debug("Save import_dir")
            g.config.var_dict["Paths"]["import_dir"] = os.path.dirname(self.filename)
            g.config.update_config()
            g.config.save_varspace()

        self.filename = qstr_encode(self.filename)
        logger.info(self.tr("File: %s selected") % self.filename)




    def load(self, plot=True):
        """
        Loads the file given by self.filename.  Also calls the command to
        make the plot.
        @param plot: if it should plot
        """
        if not QtCore.QFile.exists(self.filename):
            logger.info(self.tr("Cannot locate file: %s") % self.filename)
            self.OpenFileDialog(self.tr("Manually open file: %s") % self.filename)
            if not self.filename:
                return False  # cancelled

        self.setCursor(QtCore.Qt.CursorShape.WaitCursor)
        self.setWindowTitle("DXF2GCODE - [%s]" % self.filename)
        self.canvas.resetAll()
        self.app.processEvents()

        (name, ext) = os.path.splitext(self.filename)

        if ext.lower() == c.PROJECT_EXTENSION:
            self.loadProject(self.filename)
            return True  # kill this load operation - we opened a new one

        if ext.lower() == ".ps" or ext.lower() == ".pdf":
            # in case of PDF the two stage conversion will take place
            # as pstoedit is not able to directly convert PDF->DXF
            # Stages:
            #     1) PDF->PS (using pdftops - not pdf2ps!)
            #     2) PS->DXF (using pstoedit)
            if ext.lower() == ".pdf":
                logger.info(self.tr("Converting {0} to {1}").format("PDF", "PS"))

                # Create temporary file which will be read by the program
                tmp_filename = os.path.join(tempfile.gettempdir(), 'dxf2gcode_temp.ps')

                pdftops_cmd = g.config.vars.Filters['pdftops_cmd']
                pdftops_opt = g.config.vars.Filters['pdftops_opt']
                if len(pdftops_opt) == 1 and len(pdftops_opt[0]) == 0:
                    pdftops_opt = list()
                ps_filename = os.path.normcase(self.filename)
                cmd = [('%s' % pdftops_cmd)] + pdftops_opt + [('%s' % ps_filename),
                                                              ('%s' % os.path.normcase(tmp_filename))]
                logger.debug(cmd)
                self.filename = os.path.normcase(tmp_filename)
                try:
                    rv = subprocess.call(cmd)
                    if rv != 0:
                        self.unsetCursor()
                        QMessageBox.critical(self,
                                             self.tr("ERROR"),
                                             self.tr(
                                                 "Command:\n{0}\nreturned error code: {1}").format(' '.join(cmd), rv))
                        return True

                except OSError as e:
                    logger.error(e.strerror)
                    self.unsetCursor()
                    QMessageBox.critical(self,
                                         self.tr("ERROR"),
                                         self.tr(
                                             "Please make sure you have installed {0}, and configured it in the config file.").format("pdftops"))
                    return True

            logger.info(self.tr("Converting {0} to {1}").format("PS", "DXF"))

            # Create temporary file which will be read by the program
            tmp_filename = os.path.join(tempfile.gettempdir(), 'dxf2gcode_temp.dxf')

            pstoedit_cmd = g.config.vars.Filters['pstoedit_cmd']
            pstoedit_opt = g.config.vars.Filters['pstoedit_opt']
            if len(pstoedit_opt) == 1 and len(pstoedit_opt[0]) == 0:
                pstoedit_opt = list()
            ps_filename = os.path.normcase(self.filename)
            cmd = [('%s' % pstoedit_cmd)] + pstoedit_opt + [('%s' % ps_filename), ('%s' % os.path.normcase(tmp_filename))]
            logger.debug(cmd)
            self.filename = os.path.normcase(tmp_filename)
            try:
                rv = subprocess.call(cmd)
                if rv != 0:
                    self.unsetCursor()
                    QMessageBox.critical(self,
                                         self.tr("ERROR"),
                                         self.tr(
                                             "Command:\n{0}\nreturned error code: {1}").format(' '.join(cmd), rv))
                    return True

            except OSError as e:
                logger.error(e.strerror)
                self.unsetCursor()
                QMessageBox.critical(self,
                                     self.tr("ERROR"),
                                     self.tr("Please make sure you have installed {0}, and configured it in the config file.").format("pstoedit"))
                return True
            # If the return code was non-zero it raises a
            # subprocess.CalledProcessError.
            # subprocess.check_output()

        logger.info(self.tr('Loading file: %s') % self.filename)

        import_result = ImportDrawing(
            DxfReaderAdapter(self.application_context.config)).execute(self.filename)
        self.valuesDXF = import_result.drawing
        if not self.application_context.quiet:
            for diagnostic in import_result.diagnostics:
                QMessageBox.warning(self, diagnostic.title, diagnostic.message)

        # Output the information in the text window
        logger.info(self.tr('Loaded layers: %s') % len(self.valuesDXF.layers))
        logger.info(self.tr('Loaded blocks: %s') % len(self.valuesDXF.blocks.Entities))
        for i in range(len(self.valuesDXF.blocks.Entities)):
            layers = self.valuesDXF.blocks.Entities[i].get_used_layers()
            logger.info(self.tr('Block %i includes %i Geometries, reduced to %i Contours, used layers: %s')
                        % (i, len(self.valuesDXF.blocks.Entities[i].geo), len(self.valuesDXF.blocks.Entities[i].cont), layers))
        layers = self.valuesDXF.entities.get_used_layers()
        insert_nr = self.valuesDXF.entities.get_insert_nr()
        logger.info(self.tr('Loaded %i entity geometries; reduced to %i contours; used layers: %s; number of inserts %i')
                    % (len(self.valuesDXF.entities.geo), len(self.valuesDXF.entities.cont), layers, insert_nr))

        self.setMeasurementUnits(g.config.metric, True)

        self.makeShapes()
        if plot:
            self.plot()
        return True

    def plot(self):
        # Populate the treeViews
        self.TreeHandler.buildEntitiesTree(self.entityRoot)
        self.TreeHandler.buildLayerTree(self.layerContents)

        # Paint the canvas
        if not g.config.mode3d:
            self.canvas_scene = MyGraphicsScene()
            self.canvas.setScene(self.canvas_scene)

        self.canvas_scene.plotAll(self.shapes)
        self.setShowPathDirections()
        self.setShowDisabledPaths()
        self.liveUpdateExportRoute()

        if not g.config.mode3d:
            self.canvas.show()
            self.canvas.setFocus()
        self.canvas.autoscale()

        # After all is plotted enable the Menu entities
        self.enableToolbarButtons()

        self.automaticCutterCompensation()

        self.unsetCursor()

    def reload(self):
        """
        This function is called by the menu "File/Reload File" of the main toolbar.
        It reloads the previously loaded file (if any)
        """
        if self.filename:
            logger.info(self.tr("Reloading file: %s") % self.filename)
            self.load()

    def makeShapes(self):
        """Build the project's shape and layer model through the application service."""
        from dxf2gcode.domain.project.shape import Shape as DomainShape

        def connect_shape_callbacks(shape):
            if not g.config.mode3d:
                shape.setSelectionChangedCallback(
                    self.TreeHandler.updateShapeSelection)
                shape.setEnableDisableCallback(
                    self.TreeHandler.updateShapeEnabling)

        model = BuildDrawingModel(
            drawing=self.valuesDXF,
            config=g.config,
            shape_factory=DomainShape,
            split_line_segments=g.config.vars.General['split_line_segments'],
            transform={
                "x": self.cont_dx,
                "y": self.cont_dy,
                "scale": self.cont_scale,
                "rotation": self.cont_rotate,
                "mirrorx": self.cont_mirrorx,
                "mirrory": self.cont_mirrory,
            },
            shape_created=connect_shape_callbacks,
        ).execute()
        self.entityRoot = model.entity_root
        _log_import_filters(model)
        self.layerContents = model.layers
        self.shapes = model.shapes
        self.newNumber = len(self.shapes)

    def updateCanvasOverlay(self):
        """
        Refresh the overlays of the canvas (e.g. the scale bar) after a
        configuration change (option or measurement units).
        """
        canvas = getattr(self, 'canvas', None)
        if canvas is None:
            return
        update = getattr(canvas, 'updateScaleBar', None)
        if callable(update):
            update()

    def updateConfiguration(self, result):
        """
        Some modification occured in the configuration window, we need to save these changes into the config file.
        Once done, the signal configuration_changed is emitted, so that anyone interested in this information can connect to this signal.
        """
        if result == ConfigWindow.Applied or result == ConfigWindow.DialogCode.Accepted:
            units_before = g.config.tool_units

            # Rebuild the readonly configuration structure first: this also
            # converts all stored values if the config file's unit
            # (tool_units) was changed, so the file gets saved in a
            # consistent state and the change takes effect immediately
            # (no restart required anymore).
            g.config.update_config()
            # Write the configuration into the config file (config.cfg)
            g.config.save_varspace()

            # Assign changes to the menus (if no change occured, nothing
            # happens / otherwise QT emits a signal for the menu entry that has changed)
            self.connectToolbarToConfig(block_signals=False)

            # Inform about the changes into the configuration
            self.configuration_changed.emit()

            if g.config.tool_units != units_before:
                # The config file's unit changed: refresh the still-open
                # configuration window. Its widgets would otherwise keep
                # showing the pre-conversion values, and a further "Apply"
                # would write them back (undoing the conversion).
                self.refreshConfigWindowUnits()

    def refreshConfigWindowUnits(self):
        """
        Refresh the (possibly still open) configuration window after the
        config file's unit (tool_units) changed: re-read all widget values
        from the converted var_dict and update the unit suffixes.
        """
        window_def = self.config_window.cfg_window_def
        unit = g.config.tool_units
        distance = self.tr(" mm") if unit == 'mm' else self.tr(" in")
        speed = self.tr(" mm/min") if unit == 'mm' else self.tr(" IPS")

        section_units = {
            'Plane_Coordinates': distance,
            'Depth_Coordinates': distance,
            'Feed_Rates': speed,
        }
        for section, unit_suffix in section_units.items():
            if section not in window_def:
                continue
            for key, widget in window_def[section].items():
                if key.startswith('__'):
                    continue
                if hasattr(widget, 'setUnit'):
                    widget.setUnit(unit_suffix)

        # Re-populate all widgets from the (converted) var_dict
        self.config_window.setValuesFromConfig(window_def,
                                               g.config.var_dict,
                                               g.config.var_dict.configspec)

    def loadProject(self, filename):
        """
        Load all variables from file
        """
        project_document = LoadProject(self.project_repository).execute(filename)
        self.d2g.load(project_document)

    def saveProject(self):
        """
        Save all variables to file
        """
        prj_filename = self.showSaveDialog(self.tr('Save project to file'),
                                           self.tr("Project files (*%s)") % c.PROJECT_EXTENSION,
                                           g.config.vars.Paths['project_dir'])

        save_prj_filename = qstr_encode(prj_filename[0])

        # If Cancel was pressed
        if not save_prj_filename:
            return

        # If automatic save paths is checked keep it up to date.
        if g.config.vars.Paths['autosave_path']:
            logger.debug("Save project_dir")
            g.config.var_dict["Paths"]["project_dir"] = os.path.dirname(prj_filename[0])
            g.config.update_config()
            g.config.save_varspace()

        (beg, ende) = os.path.split(save_prj_filename)
        (fileBaseName, fileExtension) = os.path.splitext(ende)

        if fileExtension != c.PROJECT_EXTENSION:
            if not QtCore.QFile.exists(save_prj_filename):
                save_prj_filename += c.PROJECT_EXTENSION

        pyCode = self.d2g.export()
        try:
            # File open and write
            SaveProject(self.project_repository).execute(
                save_prj_filename, str_encode(pyCode))
            logger.info(self.tr("Save project to FILE was successful"))
        except IOError:
            QMessageBox.warning(g.window,
                                self.tr("Warning during Save Project As"),
                                self.tr("Cannot Save the File"))

    def closeEvent(self, e):
        logger.debug(self.tr("Closing"))
        self.saveWindowState()
        # Detach Qt-bound StreamHandler so logging.shutdown() won't crash
        # on a deleted QTextBrowser at exit. See messagebox.py / logger.py
        for handler in logger.handlers[:]:
            if isinstance(handler, logging.StreamHandler) and hasattr(handler, 'stream'):
                handler.stream = None
        e.accept()

    def restoreWindowState(self):
        self.settings.beginGroup("MainWindow")
        geometry = self.settings.value("geometry")
        state = self.settings.value("state")
        self.settings.endGroup()
        if (geometry is not None) and (state is not None):
            self.restoreGeometry(geometry)
            self.restoreState(state)

    def saveWindowState(self):
        self.settings.beginGroup("MainWindow")
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("state", self.saveState())
        self.settings.endGroup()


if __name__ == "__main__":
    """
    The main function which is executed after program start.
    """

    # Command line options must be evaluated before the configuration is
    # initialized, because the configuration folder depends on the selected
    # configuration profile.
    parser = argparse.ArgumentParser()

    parser.add_argument("filename", nargs="?")

    #    parser.add_argument("-f", "--file", dest = "filename",
    #                        help = "read data from FILENAME")
    parser.add_argument("-e", "--export", dest="export_filename",
                        help="export data to FILENAME")
    parser.add_argument("-p", "--postpro", dest="post_pro",
                        help="Post Processor to use")
    parser.add_argument("-o", "--optimize", action="store_true",
                        dest="optimize", help="optimize before export")
    parser.add_argument("-q", "--quiet", action="store_true",
                        dest="quiet", help="no GUI")
    parser.add_argument("-c", "--cfg", "--config-suffix", dest="cfg_suffix",
                        help="configuration profile to load (e.g. 'laser' loads the "
                             "profile stored in the dxf2gcode.laser folder). Without "
                             "it the profile selected last in the GUI is used.")
    #    parser.add_option("-v", "--verbose",
    #                      action = "store_true", dest = "verbose")
    options = parser.parse_args()

    # Resolve the configuration profile. An explicit command line suffix has
    # priority; otherwise the profile selected in the GUI is used (it is
    # persisted in the application settings so that the restart after a
    # profile switch picks it up). Without any selection the previous default
    # profile is used, so the previous behaviour is preserved.
    if options.cfg_suffix is not None:
        valid_suffix, suffix_message = validate_config_profile_suffix(options.cfg_suffix)
        if not valid_suffix:
            parser.error(suffix_message)
        g.folder = config_profile_folder(options.cfg_suffix)
    else:
        selected_suffix = stored_config_profile()
        g.folder = config_profile_folder(selected_suffix) if selected_suffix else config_profile_folder()

    Log = LoggerClass(logger)

    g.config = MyConfig()
    Log.set_console_handler_loglevel()

    if not g.config.vars.Logging['logfile']:
        Log.add_window_logger()
    else:
        Log.add_file_logger()

    if g.config.version_mismatch:
        if options.quiet:
            logger.error(g.config.version_mismatch)
            sys.exit(2)
        error_app = QApplication(sys.argv)
        error_message = QMessageBox(
            QMessageBox.Critical,
            QtCore.QCoreApplication.translate('MainWindow',
                                              'Configuration error'),
            g.config.version_mismatch)
        sys.exit(error_message.exec())

    if (options.quiet and options.export_filename and options.filename):
        input_extension = os.path.splitext(options.filename)[1].lower()
        if input_extension in (".dxf", ".ps", ".pdf"):
            sys.exit(_run_headless_dxf_export(
                str_decode(options.filename),
                str_decode(options.export_filename),
                options.post_pro, options.optimize))
        if input_extension == c.PROJECT_EXTENSION.lower():
            sys.exit(_run_headless_project_export(
                str_decode(options.filename),
                str_decode(options.export_filename),
                options.post_pro, options.optimize))

    app = QApplication(sys.argv)

    # Find translations independently of the process working directory.
    locale = QtCore.QLocale.system().name()
    logger.debug("locale: %s" % locale)
    translator = QtCore.QTranslator()
    locales = [locale]
    language = locale.split("_", 1)[0].split("-", 1)[0]
    if language and language not in locales:
        locales.append(language)

    from dxf2gcode.presentation.qt.translations import translation_search_paths
    translation_dirs = translation_search_paths()
    loaded_translation = False
    for translation_locale in locales:
        translation_name = "dxf2gcode_" + translation_locale
        for translation_dir in translation_dirs:
            if translator.load(translation_name, translation_dir):
                app.installTranslator(translator)
                logger.info("Loaded translation %s from %s",
                            translation_locale, translation_dir)
                loaded_translation = True
                break
        if loaded_translation:
            break
    if not loaded_translation:
        logger.info("No translation found for locale %s", locale)


    # Delay imports - needs to be done after logger and config initialization; and before the main window
    if PYQT_VERSION == 5:
        from dxf2gcode.presentation.qt.generated.dxf2gcode_ui5 import Ui_MainWindow
    else:
        from dxf2gcode.presentation.qt.generated.dxf2gcode_ui6 import Ui_MainWindow

    from dxf2gcode.domain.project.shape import Shape

    if g.config.mode3d:
        # multi-sampling has been introduced in PyQt5
        fmt = QSurfaceFormat()
        fmt.setSamples(4)
        QSurfaceFormat.setDefaultFormat(fmt)
    else:
        from dxf2gcode.presentation.qt.canvas2d import MyGraphicsScene
    application_context = create_application_context(
        config=g.config, logger=logger, quiet=options.quiet)
    window = MainWindow(app, application_context)
    g.window = window
    if not options.quiet:
        Log.add_window_logger(window.ui.messageBox)

    g.quiet = options.quiet

    # (options, args) = parser.parse_args()
    logger.debug("Started with following options:\n%s" % parser)

    if not options.quiet:
        window.show()

    if options.filename is not None:
        window.filename = str_decode(options.filename)
        window.load()

    if options.export_filename is not None:
        window.exportShapes(None, options.export_filename)

    if not options.quiet:
        # exec is no longer a reserved word in Python
        sys.exit(app.exec())
