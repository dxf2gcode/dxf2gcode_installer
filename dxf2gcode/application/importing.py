"""Application boundary for importing source drawings.

The reader is deliberately supplied by the composition root. This lets the
GUI and command-line frontends share the import use case without making the
application service depend on Qt or on a particular DXF parser.
"""

from dataclasses import dataclass
from typing import Any, Protocol, Tuple


@dataclass(frozen=True)
class ImportDiagnostic:
    """A user-presentable import warning independent of any UI toolkit."""

    code: str
    title: str
    message: str
    severity: str = "warning"


@dataclass(frozen=True)
class ImportResult:
    """Imported drawing payload and diagnostics collected while reading it."""

    drawing: Any
    diagnostics: Tuple[ImportDiagnostic, ...] = ()


class DxfReader(Protocol):
    """Port implemented by the DXF parsing adapter."""

    def read(self, filename: str) -> ImportResult:
        """Read a drawing and return its payload with any diagnostics."""


class ImportDrawing:
    """Use case that obtains a drawing through the configured reader port."""

    def __init__(self, reader: DxfReader):
        self._reader = reader

    def execute(self, filename: str) -> ImportResult:
        return self._reader.read(filename)

