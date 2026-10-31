"""Application entry point for requesting a semantic toolpath plan."""

class PlanToolpath:
    """Plan a shape through an injected planner implementation."""

    def __init__(self, planner, request_factory):
        self._planner = planner
        self._request_factory = request_factory

    def execute(self, shape, postprocessor):
        """Return the plan for a preview consumer."""
        return self.execute_result(shape, postprocessor).plan

    def execute_result(self, shape, postprocessor):
        """Snapshot boundary values and plan without a postprocessor dependency."""
        request = self._request_factory(shape, postprocessor)
        return self._planner.plan(request)
