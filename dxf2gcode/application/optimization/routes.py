"""Application workflow for optimizing per-layer export routes."""


class OptimizeRoutes:
    """Optimize layer export orders through an injected route optimizer."""

    def __init__(self, optimizer_factory, max_iterations, start_point,
                 route_settings=None):
        self._optimizer_factory = optimizer_factory
        self._max_iterations = max_iterations
        self._start_point = start_point
        self._route_settings = route_settings

    def execute(self, layers, shapes, after_layer=None):
        """Update enabled layer routes and return the last optimizer result."""
        last_optimizer = None
        total_shapes = 0
        for layer in layers:
            if not layer.exp_order:
                layer.exp_order = []
                continue

            shape_order = list(layer.exp_order)
            fixed_order = [index for index, shape_nr in enumerate(shape_order)
                           if not shapes[shape_nr].send_to_TSP]
            endpoints = []
            for shape_nr in shape_order:
                shape = shapes[shape_nr]
                if shape.Pocket:
                    endpoints.append(shape.get_start_end_points(PPocket=True))
                else:
                    endpoints.append(shape.get_start_end_points())
            endpoints.append((self._start_point, self._start_point))

            optimizer = self._optimizer_factory(
                endpoints, fixed_order, self._route_settings)
            iterations = min(self._max_iterations, len(shape_order) * 50)
            for _ in range(iterations // 50):
                optimizer.calc_next_iteration()

            layer.exp_order = [shape_order[index]
                               for index in optimizer.opt_route[1:]]
            layer.optimize()
            total_shapes += len(shape_order)
            last_optimizer = optimizer
            if after_layer is not None:
                after_layer(layer)

        return RouteOptimizationResult(total_shapes, last_optimizer)


class RouteOptimizationResult:
    """Summary of the optimizer state needed by existing GUI feedback."""

    def __init__(self, shape_count, optimizer):
        self.shape_count = shape_count
        self.optimizer = optimizer
