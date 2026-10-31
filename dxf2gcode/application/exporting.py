"""Shared application action for exporting a prepared project model."""


class ExportToolpath:
    """Serialize the current layer order through the selected postprocessor."""

    def __init__(self, postprocessor):
        self._postprocessor = postprocessor

    def execute(self, filename, output_filename, layers,
                postprocessor_index=0):
        self._postprocessor.getPostProVars(postprocessor_index)
        self._postprocessor.exportShapes(filename, output_filename, layers)
        return tuple(getattr(self._postprocessor, 'export_errors', ()) or ())
