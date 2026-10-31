"""Toolkit-independent semantic values for complete toolpath plans."""

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class ToolpathMove:
    """A linear cutting movement between two XY coordinates."""

    kind: str
    start_xy: Tuple[float, float]
    end_xy: Tuple[float, float]
    center_xy: Tuple[float, float] = None
    sweep: float = 0.0


@dataclass(frozen=True)
class ToolpathPass:
    """One ordered Z pass and the XY movements made at that depth."""

    number: int
    depth: float
    moves: Tuple[ToolpathMove, ...]


@dataclass(frozen=True)
class ToolpathPlan:
    """Immutable movement plan shared by preview and machine exporters."""

    shape_number: int
    approach_xy: Tuple[float, float]
    passes: Tuple[ToolpathPass, ...]
    workpiece_top: float
    safe_margin: float
    retract_depth: float
    feed_depth: float
    feed_xy: float
    actions: tuple = ()


@dataclass(frozen=True)
class ToolpathDiagnostic:
    """Toolkit-independent planning warning or error."""

    code: str
    severity: str
    message: str
    shape_number: Optional[int] = None
    geometry_index: Optional[int] = None
    source_message: str = ""
    message_args: tuple = ()


@dataclass(frozen=True)
class ToolpathPlanningResult:
    """A complete plan, or diagnostics explaining why none can be exported."""

    plan: Optional[ToolpathPlan]
    diagnostics: Tuple[ToolpathDiagnostic, ...] = ()

    @property
    def has_errors(self):
        return any(item.severity == "error" for item in self.diagnostics)


@dataclass(frozen=True)
class ToolpathAction:
    """A semantic movement or machine state transition, with value arguments."""

    kind: str
    args: tuple = ()
    role: str = "cut"
