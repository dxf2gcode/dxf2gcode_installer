"""Application use case for exporting a planned shape."""


class ExportShape:
    """Plan a shape once and serialize that plan for the selected machine."""

    def __init__(self, plan_toolpath, plan_exporter, diagnostic_sink=None):
        self._plan_toolpath = plan_toolpath
        self._plan_exporter = plan_exporter
        self._diagnostic_sink = diagnostic_sink

    def execute(self, shape, postprocessor):
        result = self._plan_toolpath.execute_result(shape, postprocessor)
        if self._diagnostic_sink is not None:
            for diagnostic in result.diagnostics:
                self._diagnostic_sink(diagnostic)
        if result.plan is None or result.has_errors:
            return ""
        return self._plan_exporter.export(result.plan, postprocessor)

    def plan_shape(self, shape, postprocessor):
        """Build a plan for a view without serializing it."""
        return self._plan_toolpath.execute(shape, postprocessor)
