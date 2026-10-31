"""Adapter around the existing DXF parser during the architecture migration."""

from dxf2gcode.application.importing import ImportResult
from dxf2gcode.adapters.dxf.parser import ReadDXF


class DxfReaderAdapter:
    """Expose the DXF parser through the application import contract."""

    def __init__(self, config=None):
        self._config = config

    def read(self, filename):
        # Preserve the legacy constructor call shape for callers that rely on
        # its process-global configuration fallback.
        if self._config is None:
            drawing = ReadDXF(filename)
        else:
            drawing = ReadDXF(filename, config=self._config)
        return ImportResult(
            drawing=drawing,
            diagnostics=tuple(drawing.diagnostics),
        )

