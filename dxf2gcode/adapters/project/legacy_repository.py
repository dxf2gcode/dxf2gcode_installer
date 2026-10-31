"""Repository adapter for the existing ``.d2g`` project format."""

from dxf2gcode.adapters.project.file_store import LegacyProjectFileStore
from dxf2gcode.adapters.project.legacy_d2g import decode_d2g


class LegacyProjectRepository:
    """Read validated project documents and write legacy serialized text."""

    def __init__(self, file_store=None):
        self._file_store = file_store or LegacyProjectFileStore()

    def load(self, filename):
        return decode_d2g(self._file_store.read_text(filename))

    def save(self, filename, content):
        self._file_store.write_text(filename, content)
