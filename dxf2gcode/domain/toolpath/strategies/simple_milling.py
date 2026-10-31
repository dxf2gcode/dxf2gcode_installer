"""Native planning of an uncompensated closed line contour."""

from dxf2gcode.domain.toolpath.depths import calculate_depth_passes
from dxf2gcode.domain.toolpath.movements import MovementPlan


class SimpleMillingStrategy:
    def supports(self, request):
        settings, caps = request.settings, request.capabilities
        if (settings.machine_type != "milling" or caps.output_type != "g-code" or
                not request.closed or request.compensation != 40 or
                request.pocket or request.drill or settings.slice_depth == 0 or
                settings.lead_in_mode != "off" or
                settings.lead_out_mode != "off" or settings.overcut_enabled or
                settings.break_pass != -1 or request.has_break_layers or
                request.lead_in or not request.contour or
                len(request.prepared_path) != 1 or
                request.prepared_path[0].kind != "rapid" or
                any(geo.resolved.kind != "line" for geo in request.contour)):
            return False
        geos = tuple(geo.resolved for geo in request.contour)
        tolerance = settings.point_tolerance

        def same(left, right):
            return all(abs(a - b) <= tolerance for a, b in zip(left, right))

        if (not same(geos[0].start, request.prepared_path[0].resolved.end) or
                not same(geos[-1].end, geos[0].start) or
                any(not same(left.end, right.start)
                    for left, right in zip(geos, geos[1:]))):
            return False
        depths = calculate_depth_passes(
            settings.workpiece_top, settings.slice_depth, settings.final_depth)
        return bool(depths) and depths[0] >= settings.final_depth

    def plan(self, request):
        settings = request.settings
        plan = MovementPlan(request)
        plan.geometry(request.prepared_path[0].resolved, role="approach")
        plan.add("pre_cut")
        plan.add("rapid_z", settings.workpiece_top + abs(settings.safe_margin),
                 role="approach")
        for depth in calculate_depth_passes(
                settings.workpiece_top, settings.slice_depth, settings.final_depth):
            plan.add("feed", settings.feed_depth)
            plan.add("linear_z", depth, role="plunge")
            plan.add("feed", settings.feed_xy)
            for geo in request.contour:
                plan.cut_geometry(geo)
        plan.add("feed", settings.feed_depth)
        plan.add("linear_z", settings.workpiece_top + abs(settings.safe_margin),
                 role="retract")
        plan.add("rapid_z", settings.retract_depth, role="retract")
        plan.add("post_cut")
        return plan.finish()
