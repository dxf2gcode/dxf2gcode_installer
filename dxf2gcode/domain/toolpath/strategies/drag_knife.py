"""Plan prepared drag-knife tip paths and the ramp into the workpiece."""

from math import sqrt

from dxf2gcode.domain.toolpath.movements import MovementPlan


class DragKnifeStrategy:
    def plan(self, request):
        settings = request.settings
        plan = MovementPlan(request)
        safe = settings.workpiece_top + abs(settings.safe_margin)
        plan.geometry(request.prepared_path[0].resolved, role="approach")
        plan.add("pre_cut")
        plan.add("rapid_z", safe, role="approach")
        plan.add("feed", settings.feed_depth)
        path = tuple(geo.resolved for geo in request.prepared_path[1:])
        if settings.drag_ramp_length > 0:
            self._ramp_path(plan, path, safe, settings)
        else:
            first = path[0]
            drag = first.kind == "arc" and first.drag
            plan.add("linear_z", settings.slice_depth if drag else settings.final_depth,
                     role="drag_swivel" if drag else "plunge")
            plan.add("feed", settings.feed_xy)
            plan.geometry(first, role="drag_swivel" if drag else "cut")
            for geo in path[1:]:
                is_drag = geo.kind == "arc" and geo.drag
                if is_drag or drag:
                    plan.add("feed", settings.feed_depth)
                    plan.add("linear_z",
                             settings.slice_depth if is_drag else settings.final_depth,
                             role="drag_swivel")
                    plan.add("feed", settings.feed_xy)
                drag = is_drag
                plan.cut_geometry(geo, role="drag_swivel" if is_drag else "cut")
        plan.add("feed", settings.feed_depth)
        plan.add("linear_z", safe, role="retract")
        plan.add("rapid_z", settings.retract_depth, role="retract")
        plan.add("post_cut")
        return plan.finish()

    def _ramp_path(self, plan, path, start_z, settings):
        remaining = settings.drag_ramp_length
        finished = drag = False
        for geo in path:
            is_drag = geo.kind == "arc" and geo.drag
            if not finished and remaining > 0 and not is_drag:
                remaining = self._ramp_geometry(
                    plan, geo, remaining, settings.drag_ramp_length,
                    start_z, settings.final_depth)
                if remaining > 0:
                    continue
                finished = True
                plan.add("feed", settings.feed_xy)
                continue
            if is_drag:
                finished = True
                plan.add("feed", settings.feed_depth)
                plan.add("linear_z", settings.slice_depth, role="drag_swivel")
                plan.add("feed", settings.feed_xy)
                drag = True
            elif drag:
                plan.add("feed", settings.feed_depth)
                plan.add("linear_z", settings.final_depth, role="drag_swivel")
                plan.add("feed", settings.feed_xy)
                drag = False
            plan.cut_geometry(geo, role="drag_swivel" if is_drag else "cut")

    @staticmethod
    def _ramp_geometry(plan, geo, remaining, ramp_length, start_z, end_z):
        if geo.length <= 0:
            return remaining
        used = min(geo.length, remaining)
        steps = max(2, int(round(used)))
        if geo.kind == "line":
            factor = used / geo.length
            end = tuple(a + (b - a) * factor for a, b in zip(geo.start, geo.end))
            points = [
                tuple(a + (b - a) * (float(index) / steps)
                      for a, b in zip(geo.start, end))
                for index in range(steps + 1)]
        elif geo.kind == "arc":
            end_angle = geo.start_angle + geo.sweep * (used / geo.length)
            points = [
                geo.arc_point(geo.start_angle +
                              (end_angle - geo.start_angle) * (float(index) / steps))
                for index in range(steps + 1)]
        else:
            return remaining
        previous, covered = points[0], 0.0
        for point in points[1:]:
            covered += sqrt(sum((a - b) ** 2 for a, b in zip(previous, point)))
            z = start_z + (end_z - start_z) * (covered / ramp_length)
            plan.add("linear_z", z, role="ramp")
            plan.add("linear_xy", previous, point, role="ramp")
            previous = point
        return remaining - used
