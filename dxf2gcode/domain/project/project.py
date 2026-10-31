# -*- coding: utf-8 -*-

############################################################################
#
#   Copyright (C) 2015
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

import logging
import hashlib
from dataclasses import asdict

from dxf2gcode.domain.geometry.point import Point
from dxf2gcode.domain.toolpath.customgcode import CustomGCode
from dxf2gcode.domain.project.layercontent import Layers, Shapes
from dxf2gcode.domain.project.tool_settings import ToolSettings
from dxf2gcode.domain.toolpath.leadmove import LEAD_DEFAULT, OVERCUT_DEFAULT
import dxf2gcode.bootstrap.runtime_state as g

from dxf2gcode.presentation.qt.qt_compat import QtCore
from dxf2gcode.adapters.project.legacy_d2g import (
    CURRENT_D2G_VERSION, D2G_HEADER, SUPPORTED_D2G_VERSIONS,
    LegacyProjectDocument, decode_d2g)

logger = logging.getLogger("Core.Project")

def _safe_load_project(self, content):
    """Compatibility facade for the safe legacy project decoder."""
    document = (content if isinstance(content, LegacyProjectDocument)
                else decode_d2g(content))
    for name, value in document.values.items():
        setattr(self, name, value)
    return document

class Project(object):
    header = D2G_HEADER
    supported_versions = list(SUPPORTED_D2G_VERSIONS)
    version = CURRENT_D2G_VERSION

    def __init__(self, parent):
        self.parent = parent

        self.file = None
        self.point_tol = None
        self.fitting_tol = None
        self.scale = None
        self.rot = None
        self.wpzero_x = None
        self.wpzero_y = None
        self.mirrorx = None
        self.mirrory = None
        self.split_lines = None
        self.aut_cut_com = None
        self.machine_type = None

        self.layers = None

    def tr(self, string_to_translate):
        """
        Translate a string using the QCoreApplication translation framework
        @param: string_to_translate: a unicode string
        @return: the translated unicode string if it was possible to translate
        """
        return str(QtCore.QCoreApplication.translate('Project',
                                                           string_to_translate))

    def get_hash(self, shape, version, compleet=True):
        reverse = False
        if not shape.cw:
            reverse = True
            shape.reverse()

        shape_iter = shape.geos if version < 1.2 else shape.geos.abs_iter()  # new versions look at absolute values
        geos = [geo.save_v1() for geo in shape_iter]
        if reverse:
            shape.reverse()
        if compleet:
            return hashlib.sha1(''.join(sorted(geos)).encode('utf-8')).hexdigest()
        #If it's not a compleet reload change the hash to something more identical. This might enable a reload with previous settings
        #For Rot / sca / wp move etc. hash will not be identical with above algorithm as they are changed. but the Shape.nr will stay the same.
        else:
            return hashlib.sha1(('%s' %(shape.nr)).encode('utf-8')).hexdigest()
        

    def export(self,compleet=True):
        self.parent.TreeHandler.updateExportOrder(True)
        layers = []
        for layer in self.parent.layerContents:
            shapes = []
            for nr in layer.exp_order_complete:
                shape = layer.shapes[nr]
                if isinstance(shape, CustomGCode):
                    shapes.append({'gcode': shape.gcode,
                                   'name': shape.name,
                                   'disabled': shape.disabled})
                else:
                    stpoint = shape.get_start_end_points(True)
                    shapes.append({'hash_': self.get_hash(shape, Project.version, compleet),
                                   'cut_cor': shape.cut_cor,
                                   'Pocket_Mill': shape.Pocket,
                                   'Drill': shape.Drill,
                                   'cw': shape.cw,
                                   'send_to_TSP': shape.send_to_TSP,
                                   'disabled': shape.disabled,
                                   'start_mill_depth': shape.axis3_start_mill_depth,
                                   'slice_depth': shape.axis3_slice_depth,
                                   'mill_depth': shape.axis3_mill_depth,
                                   'milling_offset': getattr(shape, 'milling_offset', 0.0),
                                   'f_g1_plane': shape.f_g1_plane,
                                   'f_g1_depth': shape.f_g1_depth,
                                   'break_pass': getattr(shape, 'break_pass', -1),
                                   'overcut_enabled': getattr(shape, 'overcut_enabled', OVERCUT_DEFAULT),
                                   'overcut_enabled_overridden': getattr(shape, 'overcut_enabled_overridden', False),
                                   'lead_in_mode': getattr(shape, 'lead_in_mode', LEAD_DEFAULT),
                                   'lead_out_mode': getattr(shape, 'lead_out_mode', LEAD_DEFAULT),
                                   'lead_in_mode_overridden': getattr(shape, 'lead_in_mode_overridden', False),
                                   'lead_out_mode_overridden': getattr(shape, 'lead_out_mode_overridden', False),
                                   'start_x': stpoint.x,
                                   'start_y': stpoint.y})
                    if getattr(shape, "tool_override", None) is not None:
                        shapes[-1]["tool_override"] = asdict(shape.tool_override)
            layers.append({'name': layer.name,
                           'tool_nr': layer.tool_nr,
                           'diameter': layer.tool_diameter,
                           'speed': layer.speed,
                           'lead_radius': getattr(layer, 'lead_radius', 0.0),
                           'lead_length': getattr(layer, 'lead_length', 0.0),
                           'milling_offset': getattr(layer, 'milling_offset', 0.0),
                           'lead_in_mode': getattr(layer, 'lead_in_mode', 'default'),
                           'lead_out_mode': getattr(layer, 'lead_out_mode', 'default'),
                           'overcut_enabled': getattr(layer, 'overcut_enabled', OVERCUT_DEFAULT),
                           'overcut_length': getattr(layer, 'overcut_length', 0.0),
                           'lead_in_mode_overridden': getattr(layer, 'lead_in_mode_overridden', False),
                           'lead_out_mode_overridden': getattr(layer, 'lead_out_mode_overridden', False),
                           'lead_radius_overridden': getattr(layer, 'lead_radius_overridden', False),
                           'lead_length_overridden': getattr(layer, 'lead_length_overridden', False),
                           'overcut_length_overridden': getattr(layer, 'overcut_length_overridden', False),
                           'overcut_enabled_overridden': getattr(layer, 'overcut_enabled_overridden', False),
                           'retract': layer.axis3_retract,
                           'safe_margin': layer.axis3_safe_margin,
                           'shapes': shapes})

        pyCode = Project.header % str(Project.version) + '''
d2g.file = "''' + self.parent.filename + '''"
d2g.point_tol = ''' + str(g.config.point_tolerance) + '''
d2g.fitting_tol = ''' + str(g.config.fitting_tolerance) + '''
d2g.scale = ''' + str(self.parent.cont_scale) + '''
d2g.rot = ''' + str(self.parent.cont_rotate) + '''
d2g.wpzero_x = ''' + str(self.parent.cont_dx) + '''
d2g.wpzero_y = ''' + str(self.parent.cont_dy) + '''
d2g.mirrorx = ''' + str(self.parent.cont_mirrorx) + '''
d2g.mirrory = ''' + str(self.parent.cont_mirrory) + '''
d2g.split_lines = ''' + str(self.parent.ui.actionSplitLineSegments.isChecked()) + '''
d2g.aut_cut_com = ''' + str(self.parent.ui.actionAutomaticCutterCompensation.isChecked()) + '''
d2g.machine_type = "''' + g.config.machine_type + '''"
d2g.layers = ''' + str(layers)
        return pyCode

    def load(self, content, compleet=True):
        document = _safe_load_project(self, content)
        version = document.version

        if compleet:
            self.parent.filename = self.file
            g.config.point_tolerance = self.point_tol
            g.config.fitting_tolerance = self.fitting_tol

        # If one of scale / move / rot variables has changed the reload will not identify the shape to be similar.
        # Therefore try to move those variables at the end and do a second reload afterwards.
            self.parent.cont_scale = self.scale
            self.parent.cont_rotate = self.rot
            self.parent.cont_dx = self.wpzero_x
            self.parent.cont_dy = self.wpzero_y

            #New Variable with version 1.3
            if version<1.3:
                self.parent.cont_mirrorx = False
                self.parent.cont_mirrory = False
            else:
                self.parent.cont_mirrorx = self.mirrorx
                self.parent.cont_mirrory = self.mirrory

            g.config.vars.General['split_line_segments'] = self.split_lines
            g.config.vars.General['automatic_cutter_compensation'] = self.aut_cut_com
            g.config.machine_type = self.machine_type

            self.parent.connectToolbarToConfig(True)
            if not self.parent.load(False):
                self.parent.unsetCursor()
                return

        name_layers = dict((layer.name, layer) for layer in self.parent.layerContents)
        # dict comprehensions are supported since Py2.7
        # name_layers = {layer.name: layer for layer in self.parent.layerContents}

        layers = []
        for parent_layer in self.layers:
            if parent_layer['name'] in name_layers:
                layer = name_layers[parent_layer['name']]
                layer.tool_nr = parent_layer['tool_nr']
                layer.tool_diameter = parent_layer['diameter']
                layer.speed = parent_layer['speed']
                # Older project files do not contain the additional offset;
                # fall back to the neutral value (unchanged behaviour).
                layer.milling_offset = parent_layer.get('milling_offset', 0.0)
                # The radius and the length of the lead in / lead out are
                # common to both directions and they are defined per tool.
                # Older project files do not contain them: they fall back to
                # the values of the tool of the layer.
                tool = g.config.vars.Tool_Parameters[str(layer.tool_nr)]
                if tool is None:
                    tool = g.config.vars.Tool_Parameters['1']
                default_radius = tool['lead_radius']
                if default_radius is None:
                    default_radius = 0.0
                default_length = tool['lead_length']
                if default_length is None:
                    default_length = 0.0
                layer.lead_radius = parent_layer.get('lead_radius',
                                                     default_radius)
                layer.lead_length = parent_layer.get('lead_length',
                                                     default_length)
                # The lead in / lead out / overcut settings were added later:
                # older project files fall back to the global defaults (the
                # layer uses the default method of the configuration file).
                layer.lead_in_mode = parent_layer.get('lead_in_mode', 'default')
                layer.lead_out_mode = parent_layer.get('lead_out_mode', 'default')
                layer.overcut_enabled = parent_layer.get('overcut_enabled', OVERCUT_DEFAULT)
                layer.overcut_length = parent_layer.get('overcut_length', 0.0)
                # The values which were set by a layer name must not be
                # overwritten by the global defaults.
                layer.lead_in_mode_overridden = parent_layer.get(
                    'lead_in_mode_overridden', False)
                layer.lead_out_mode_overridden = parent_layer.get(
                    'lead_out_mode_overridden', False)
                layer.lead_radius_overridden = parent_layer.get(
                    'lead_radius_overridden', False)
                layer.lead_length_overridden = parent_layer.get(
                    'lead_length_overridden', False)
                layer.overcut_length_overridden = parent_layer.get(
                    'overcut_length_overridden', False)
                layer.overcut_enabled_overridden = parent_layer.get(
                    'overcut_enabled_overridden', False)

                layer.axis3_retract = parent_layer['retract']
                layer.axis3_safe_margin = parent_layer['safe_margin']

                # hash_shapes = dict((self.get_hash(shape), shape) for shape in layer.shapes)
                # dict comprehensions are supported since Py2.7
                # hash_shapes = {self.get_hash(shape): shape for shape in layer.shapes}
                hash_shapes = dict()
                for shape in layer.shapes:
                    shape_hash = self.get_hash(shape, version, compleet)
                    if shape_hash in hash_shapes:
                        hash_shapes[shape_hash].insert(0, shape)
                    else:
                        hash_shapes[shape_hash] = [shape]

                

                shapes = []
                for parent_shape in parent_layer['shapes']:
                    if 'gcode' in parent_shape:
                        shape = CustomGCode(parent_shape['name'], self.parent.newNumber, parent_shape['gcode'], layer)
                        self.parent.newNumber += 1
                        shape.disabled = parent_shape['disabled']
                        shapes.append(shape)
                    elif parent_shape['hash_'] in hash_shapes:
                        shape_list = hash_shapes[parent_shape['hash_']]
                        shape = shape_list.pop()
                        if len(shape_list) == 0:
                            del hash_shapes[parent_shape['hash_']]
                        shape.cut_cor = parent_shape['cut_cor']
                        shape.Pocket = parent_shape['Pocket_Mill']
                        shape.Drill = parent_shape['Drill']
                        shape.send_to_TSP = parent_shape['send_to_TSP']
                        shape.disabled = parent_shape['disabled']
                        shape.axis3_start_mill_depth = parent_shape['start_mill_depth']
                        shape.axis3_slice_depth = parent_shape['slice_depth']
                        shape.axis3_mill_depth = parent_shape['mill_depth']
                        # Older project files do not contain the additional
                        # offset; fall back to the neutral value.
                        shape.milling_offset = parent_shape.get('milling_offset', 0.0)
                        tool_override = parent_shape.get("tool_override")
                        shape.tool_override = (ToolSettings(**tool_override)
                                               if tool_override else None)
                        shape.f_g1_plane = parent_shape['f_g1_plane']
                        shape.f_g1_depth = parent_shape['f_g1_depth']
                        # Older project files do not contain break_pass;
                        # restore the default "last pass" (auto) in that case.
                        shape.break_pass = parent_shape.get('break_pass', -1)
                        # The overcut is a setting of the shape. Older project
                        # files stored it on the layer: a shape without an own
                        # value follows the layer (which was loaded above).
                        shape.overcut_enabled = parent_shape.get(
                            'overcut_enabled', OVERCUT_DEFAULT)
                        shape.overcut_enabled_overridden = parent_shape.get(
                            'overcut_enabled_overridden', False)
                        # The lead in / lead out methods are settings of the
                        # shape too. Older project files stored them on the
                        # layer: a shape without an own value follows the layer
                        # (which was loaded above).
                        shape.lead_in_mode = parent_shape.get(
                            'lead_in_mode', LEAD_DEFAULT)
                        shape.lead_out_mode = parent_shape.get(
                            'lead_out_mode', LEAD_DEFAULT)
                        shape.lead_in_mode_overridden = parent_shape.get(
                            'lead_in_mode_overridden', False)
                        shape.lead_out_mode_overridden = parent_shape.get(
                            'lead_out_mode_overridden', False)

                        if parent_shape['cw'] != shape.cw:
                            shape.reverse()
                        shape.setNearestStPoint(Point(parent_shape['start_x'], parent_shape['start_y']))
                        shapes.append(shape)
                new_shapes = set(layer.shapes) - set(shapes);
                shapes.extend(new_shapes)  # add "new" shapes to the end
                layer.shapes = Shapes(shapes)  # overwrite original
                if len(new_shapes) > 0:
                    logger.info(self.tr("New/Unrecognized shapes added for layer:%s; %s") %
                                (layer.name, [shape.nr for shape in new_shapes]))

                layers.append(layer)

        layers.extend(set(self.parent.layerContents) - set(layers))  # add "new" layers to the end
        self.parent.layerContents = Layers(layers)  # overwrite original
        self.parent.plot()

    def reload(self, compleet=True):
        if self.parent.filename:
            self.parent.setCursor(QtCore.Qt.CursorShape.WaitCursor)
            self.parent.canvas.resetAll()
            self.parent.app.processEvents()
            pyCode = self.export(compleet)
            self.parent.makeShapes()
            self.load(pyCode, compleet)

    def small_reload(self,):
        self.reload(False)
