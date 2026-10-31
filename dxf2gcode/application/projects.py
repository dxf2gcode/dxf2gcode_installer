"""Application use cases for reading and writing DXF2GCODE projects."""


class LoadProject:
    """Load a validated project document through the configured repository."""

    def __init__(self, repository):
        self._repository = repository

    def execute(self, filename):
        return self._repository.load(filename)


class SaveProject:
    """Persist an already serialized project through the configured repository."""

    def __init__(self, repository):
        self._repository = repository

    def execute(self, filename, content):
        self._repository.save(filename, content)

