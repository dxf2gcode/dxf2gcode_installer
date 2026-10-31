"""Immutable inputs shared by the toolpath planning strategies."""

from dataclasses import dataclass, replace
from typing import Optional, Tuple
from math import cos, sin

XY = Tuple[float, float]


@dataclass(frozen=True)
class PathGeometry:
    kind: str
    start: XY
    end: XY
    length: float = 0.0
    center: Optional[XY] = None
    radius: float = 0.0
    start_angle: float = 0.0
    end_angle: float = 0.0
    sweep: float = 0.0
    drag: bool = False
    height: float = 0.0
    xy_feed: float = 0.0
    z_feed: float = 0.0
    safe_depth: float = 0.0
    depth: float = 0.0
    retract_depth: float = 0.0
    absolute: Optional["PathGeometry"] = None

    @property
    def resolved(self):
        return self.absolute if self.absolute is not None else self

    def reversed(self):
        return replace(
            self, start=self.end, end=self.start,
            start_angle=self.end_angle, end_angle=self.start_angle,
            sweep=-self.sweep,
            absolute=self.absolute.reversed() if self.absolute is not None else None)

    def arc_point(self, angle):
        return (self.center[0] + self.radius * cos(angle),
                self.center[1] + self.radius * sin(angle))


def reverse_chain(geometries):
    return tuple(geometry.reversed() for geometry in reversed(geometries))


@dataclass(frozen=True)
class MachiningSettings:
    machine_type: str = "milling"
    machine_compensation: bool = False
    workpiece_top: float = 0.0
    slice_depth: float = 1.0
    final_depth: float = -1.0
    feed_xy: float = 500.0
    feed_depth: float = 100.0
    safe_margin: float = 1.0
    retract_depth: float = 5.0
    break_pass: int = -1
    lead_in_mode: str = "off"
    lead_out_mode: str = "off"
    overcut_enabled: bool = False
    tool_radius: float = 0.0
    lead_radius: float = 0.0
    lead_length: float = 0.0
    overcut_length: float = 0.0
    lead_side: int = 1
    drag_ramp_length: float = 0.0
    point_tolerance: float = 0.001


@dataclass(frozen=True)
class MachineCapabilities:
    output_type: str = "g-code"
    repeat_drill_move: bool = False
    compensation_outside_piece: bool = True
    cancel_compensation_for_depth: bool = False
    post_decimals: int = 3
    max_arc_radius: float = 1000000.0
    arcs_as_lines: bool = False
    counterclockwise_arcs_only: bool = False
    fitting_tolerance: float = 0.001
    absolute_coordinates: bool = True


@dataclass(frozen=True)
class PlanningState:
    """Initial modal values needed by the existing tab rules.

    z_word is deliberately distinct from the physical Z coordinate: existing
    incremental profiles base tab eligibility and restoration on that word.
    Keeping both preserves their output until the rule is changed explicitly.
    """
    feed: float = 0.0
    z_word: float = 0.0
    last_absolute_z: float = 0.0


@dataclass(frozen=True)
class ToolpathRequest:
    shape_number: int
    settings: MachiningSettings
    capabilities: MachineCapabilities
    contour: Tuple[PathGeometry, ...] = ()
    prepared_path: Tuple[PathGeometry, ...] = ()
    split_contour: Tuple[PathGeometry, ...] = ()
    lead_in: Tuple[PathGeometry, ...] = ()
    lead_nominal_index: int = 0
    closed: bool = True
    compensation: int = 40
    pocket: bool = False
    drill: bool = False
    has_break_layers: bool = False
    start_error: str = ""
    literal: Optional[str] = None
    initial_state: PlanningState = PlanningState()
