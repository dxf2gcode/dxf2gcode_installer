"""Application actions for shape-level machining settings."""

from dxf2gcode.domain.toolpath.leadmove import OVERCUT_DEFAULT
from dxf2gcode.domain.toolpath.customgcode import CustomGCode
from dxf2gcode.domain.project.tool_settings import ToolSettings, effective_tool


class AssignTool:
    """Assign a tool to selected shapes or explicitly selected whole layers."""

    def execute(self, shapes, layers, number, profile):
        tool = ToolSettings.from_profile(number, profile)
        changed = []
        whole_layers = tuple(layers)
        for layer in whole_layers:
            for name in ToolSettings.__dataclass_fields__:
                if (name == "overcut_length" and
                        getattr(layer, "overcut_length_overridden", False)):
                    continue
                setattr(layer, name, getattr(tool, name))
            for shape in layer.shapes:
                if isinstance(shape, CustomGCode):
                    continue
                shape.tool_override = None
                shape.milling_offset = profile["milling_offset"]
                changed.append(shape)
        for shape in shapes:
            if shape in changed or isinstance(shape, CustomGCode):
                continue
            if effective_tool(shape).tool_nr == tool.tool_nr:
                continue
            shape.tool_override = tool
            shape.milling_offset = profile["milling_offset"]
            changed.append(shape)
        return tuple(changed)


class SetShapeOvercut:
    """Apply or clear the overcut override on closed contours."""

    def execute(self, shapes, enabled, use_default=False):
        updated = []
        for shape in shapes:
            if not getattr(shape, "closed", False):
                continue
            shape.overcut_enabled = enabled
            shape.overcut_enabled_overridden = not use_default
            updated.append(shape)
        return tuple(updated)


class SetShapeLeadMode:
    """Apply a lead mode override or restore inherited configuration values."""

    PARAMETERS = frozenset(("lead_in_mode", "lead_out_mode"))

    def execute(self, shapes, parameter, mode, use_default=False):
        if parameter not in self.PARAMETERS:
            raise ValueError("unsupported lead mode: %s" % parameter)
        updated = []
        for shape in shapes:
            setattr(shape, parameter, mode)
            setattr(shape, parameter + "_overridden", not use_default)
            updated.append(shape)
        return tuple(updated)


class SetShapeBreakPass:
    """Set the pass from which a shape's tab or break geometry is processed."""

    def execute(self, shapes, break_pass):
        break_pass = int(break_pass)
        if break_pass < -1:
            raise ValueError("break_pass must be -1 or a non-negative pass")
        updated = []
        for shape in shapes:
            shape.break_pass = break_pass
            updated.append(shape)
        return tuple(updated)


class UpdateShapeParameters:
    """Apply validated machining parameter values to selected shapes."""

    PARAMETERS = frozenset((
        "axis3_slice_depth", "f_g1_plane", "f_g1_depth",
        "axis3_start_mill_depth", "axis3_mill_depth", "milling_offset",
    ))

    def execute(self, shapes, parameter, value):
        if parameter not in self.PARAMETERS:
            raise ValueError("unsupported shape parameter: %s" % parameter)
        changed = []
        for shape in shapes:
            if getattr(shape, parameter) != value:
                setattr(shape, parameter, value)
                changed.append(shape)
        return tuple(changed)


class UpdateLayerParameters:
    """Apply layer-level tool and depth parameters from a presentation action."""

    PARAMETERS = frozenset((
        "axis3_retract", "axis3_safe_margin", "tool_nr", "tool_diameter",
        "speed", "lead_radius", "lead_length", "overcut_length",
        "milling_offset", "axis3_slice_depth", "f_g1_plane", "f_g1_depth",
        "axis3_start_mill_depth", "axis3_mill_depth", "lead_in_mode",
        "lead_out_mode", "overcut_enabled",
    ))

    def execute(self, layers, **values):
        unsupported = set(values).difference(self.PARAMETERS)
        if unsupported:
            raise ValueError("unsupported layer parameters: %s" %
                             ", ".join(sorted(unsupported)))
        updated = []
        for layer in layers:
            for parameter, value in values.items():
                setattr(layer, parameter, value)
            updated.append(layer)
        return tuple(updated)


class ApplyLayerOvercutDefaults:
    """Refresh a layer's tool-sourced overcut values unless overridden."""

    def execute(self, layer, config):
        updated = False
        if not getattr(layer, "overcut_length_overridden", False):
            try:
                tool = config.vars.Tool_Parameters[str(layer.tool_nr)]
                new_length = tool["overcut_length"]
            except (KeyError, AttributeError, TypeError):
                new_length = 0.0
            if layer.overcut_length != new_length:
                UpdateLayerParameters().execute(
                    [layer], overcut_length=new_length)
                updated = True

            if getattr(layer, "overcut_enabled", OVERCUT_DEFAULT) != \
                    OVERCUT_DEFAULT:
                UpdateLayerParameters().execute(
                    [layer], overcut_enabled=OVERCUT_DEFAULT)
                updated = True
        return updated


class AutomaticCutterCompensation:
    """Assign alternating inside/outside compensation by contour containment."""

    def execute(self, layers, enabled, machine_type):
        if not enabled or machine_type != "milling":
            return ()
        changed = []
        for layer in layers:
            if not layer.automaticCutterCompensationEnabled():
                continue
            new_order = []
            outside_compensation = True
            shapes_left = list(layer.shapes)
            while shapes_left:
                deferred = []
                for shape in shapes_left:
                    if self._is_contained_by_other(shape, shapes_left):
                        deferred.append(shape)
                        continue
                    shape.cut_cor = 41 if outside_compensation == shape.cw else 42
                    changed.append(shape)
                    new_order.append(shape.nr)
                if len(deferred) == len(shapes_left):
                    # Degenerate containment cycles must not hang the GUI/CLI.
                    shape = deferred.pop(0)
                    shape.cut_cor = 41 if outside_compensation == shape.cw else 42
                    changed.append(shape)
                    new_order.append(shape.nr)
                shapes_left = deferred
                outside_compensation = not outside_compensation
            layer.exp_order = list(reversed(new_order))
        return tuple(changed)

    @staticmethod
    def _is_contained_by_other(shape, shapes):
        if isinstance(shape, CustomGCode):
            return False
        return any(
            shape is not outer and not isinstance(outer, CustomGCode) and
            shape.BB.iscontained(outer.BB)
            for outer in shapes)
