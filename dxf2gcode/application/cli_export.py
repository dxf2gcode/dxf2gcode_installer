"""Headless import, project-model construction and export workflow."""

import os

from dxf2gcode.domain.geometry.point import Point
from dxf2gcode.domain.toolpath.stmove import StMove
from dxf2gcode.application.optimization.routes import OptimizeRoutes
from dxf2gcode.application.shapes import AutomaticCutterCompensation
from dxf2gcode.application.exporting import ExportToolpath
from dxf2gcode.adapters.dxf.reader import DxfReaderAdapter
from dxf2gcode.application.drawings import BuildDrawingModel, DrawingModel
from dxf2gcode.application.importing import ImportDrawing
from dxf2gcode.domain.project.shape import Shape
from dxf2gcode.domain.project.project import Project


class ExportDrawing:
    """Run the shared import, model-building, optimization and export services."""

    def __init__(self, import_drawing, build_model, postprocessor, config,
                 optimizer_factory=None):
        self._import_drawing = import_drawing
        self._build_model = build_model
        self._postprocessor = postprocessor
        self._config = config
        self._optimizer_factory = optimizer_factory

    def execute(self, filename, output_filename, optimize=False,
                postprocessor_index=0, import_filename=None):
        import_result = self._import_drawing.execute(import_filename or filename)
        model = self._build_model(import_result.drawing)
        self.export_model(model, filename, output_filename, optimize,
                          postprocessor_index)
        return model, import_result.diagnostics

    def export_model(self, model, filename, output_filename, optimize=False,
                     postprocessor_index=0):
        for layer in model.layers:
            enabled_shapes = [shape for shape in layer.shapes
                              if not shape.isDisabled()]
            layer.exp_order = [shape.nr for shape in enabled_shapes]

        AutomaticCutterCompensation().execute(
            model.layers.non_break_layer_iter(),
            self._config.vars.General['automatic_cutter_compensation'],
            self._config.machine_type)
        if optimize and self._optimizer_factory is not None:
            coordinates = self._config.vars.Plane_Coordinates
            optimizer = OptimizeRoutes(
                optimizer_factory=self._optimizer_factory,
                max_iterations=self._config.vars.Route_Optimisation[
                    'max_iterations'],
                start_point=Point(coordinates['axis1_start_end'],
                                  coordinates['axis2_start_end']),
                route_settings=self._config.vars.Route_Optimisation)
            optimizer.execute(model.layers.non_break_layer_iter(),
                              model.shapes)

        for layer in model.layers:
            layer.exp_order_complete = [
                layer.shapes.index(model.shapes[shape_nr])
                for shape_nr in layer.exp_order]

        for shape in model.shapes:
            shape.stmove = StMove(shape)

        ExportToolpath(self._postprocessor).execute(
            filename, output_filename, model.layers, postprocessor_index)


class _HeadlessProjectSession:
    """Small compatibility context for loading .d2g without MainWindow."""

    def __init__(self, config, project_filename):
        self.config = config
        self.project_filename = project_filename
        self.filename = None
        self.cont_scale = 1.0
        self.cont_rotate = 0.0
        self.cont_dx = 0.0
        self.cont_dy = 0.0
        self.cont_mirrorx = False
        self.cont_mirrory = False
        self.layerContents = []
        self.shapes = []
        self.newNumber = 0
        self.drawing = None
        self.entityRoot = None
        self.loaded = False
        self.diagnostics = ()
        self.excluded_layers = ()

    def connectToolbarToConfig(self, block_signals=True):
        """The GUI-only toolbar binding has no headless equivalent."""

    def load(self, plot=False):
        filename = self.filename
        if not filename:
            return False
        if not os.path.isabs(filename):
            filename = os.path.join(
                os.path.dirname(self.project_filename), filename)
        if not os.path.isfile(filename):
            return False
        self.filename = filename
        result = ImportDrawing(DxfReaderAdapter(self.config)).execute(filename)
        self.diagnostics = result.diagnostics
        self.drawing = result.drawing
        model = BuildDrawingModel(
            drawing=result.drawing,
            config=self.config,
            shape_factory=Shape,
            split_line_segments=self.config.vars.General[
                'split_line_segments'],
            transform={
                'x': self.cont_dx, 'y': self.cont_dy,
                'scale': self.cont_scale, 'rotation': self.cont_rotate,
                'mirrorx': self.cont_mirrorx,
                'mirrory': self.cont_mirrory,
            }).execute()
        self.layerContents = model.layers
        self.shapes = model.shapes
        self.entityRoot = model.entity_root
        self.excluded_layers = model.excluded_layers
        self.newNumber = len(self.shapes)
        self.loaded = True
        return True

    def unsetCursor(self):
        """Compatibility no-op for the old project loader."""

    def plot(self):
        """Project loading calls plot after restoring the model; export does not."""


class ExportProject:
    """Load a legacy .d2g model and export it without constructing Qt UI."""

    def __init__(self, project_repository, config, postprocessor,
                 optimizer_factory=None):
        self._repository = project_repository
        self._config = config
        self._postprocessor = postprocessor
        self._optimizer_factory = optimizer_factory

    def execute(self, project_filename, output_filename, optimize=False,
                postprocessor_index=0):
        session = _HeadlessProjectSession(self._config, project_filename)
        project = Project(session)
        project_document = self._repository.load(project_filename)
        project.load(project_document)
        if not session.loaded:
            raise FileNotFoundError(
                "project source drawing could not be loaded: %s" %
                project_document.values.get('file'))

        source_filename = session.filename
        if not source_filename:
            source_filename = project_filename
        model = DrawingModel(session.entityRoot, session.layerContents,
                             session.shapes, session.excluded_layers)
        exporter = ExportDrawing(
            import_drawing=None, build_model=None,
            postprocessor=self._postprocessor, config=self._config,
            optimizer_factory=self._optimizer_factory)
        exporter.export_model(model, source_filename, output_filename,
                              optimize, postprocessor_index)
        return model, session.diagnostics
