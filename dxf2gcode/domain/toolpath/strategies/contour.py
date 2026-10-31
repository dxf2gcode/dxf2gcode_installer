"""Plan contour passes, compensation, tabs and prepared pocket geometry."""

from dataclasses import replace

from dxf2gcode.domain.toolpath.depths import calculate_depth_passes
from dxf2gcode.domain.toolpath.diagnostics import (
    EXIT_ERROR, INITIAL_DEPTH, INVERTED_RANGE, MISSING_LEAD, ZERO_SLICE, diagnostic)
from dxf2gcode.domain.toolpath.inputs import reverse_chain
from dxf2gcode.domain.toolpath.movements import MovementPlan
from dxf2gcode.domain.toolpath.plan import ToolpathPlanningResult


class ContourStrategy:
    def __init__(self, exit_geometry):
        self._exit_geometry = exit_geometry

    def plan(self, request):
        settings, caps = request.settings, request.capabilities
        output = MovementPlan(request)
        diagnostics = []
        compensation = request.compensation
        software_comp = ((compensation != 40 or request.pocket) and
                         not settings.machine_compensation and not request.drill)
        geos = (request.prepared_path[1 + len(request.lead_in):]
                if software_comp else request.contour)
        if software_comp:
            compensation = 40
        if compensation in (41, 42) and settings.lead_in_mode == "off":
            return ToolpathPlanningResult(None, (diagnostic(
                request, "compensation.missing_lead",
                MISSING_LEAD, request.shape_number),))
        if not geos:
            return ToolpathPlanningResult(output.finish())

        depths = calculate_depth_passes(
            settings.workpiece_top, settings.slice_depth, settings.final_depth,
            single_pass=(caps.output_type == "dxf" or
                         (request.drill and not caps.repeat_drill_move)))
        warning_cases = (
            (settings.slice_depth == 0, "depth.zero_slice",
             ZERO_SLICE, (request.shape_number,)),
            (settings.workpiece_top < settings.final_depth, "depth.inverted_range",
             INVERTED_RANGE,
             (settings.workpiece_top, settings.final_depth)),
            (depths[0] < settings.final_depth, "depth.initial_below_final",
             INITIAL_DEPTH,
             (depths[0], settings.final_depth)))
        for condition, code, source, args in warning_cases:
            if condition:
                diagnostics.append(diagnostic(
                    request, code, source, *args, severity="warning"))

        split = request.split_contour
        heights = [geo.height for geo in split if geo.kind == "break"]
        if request.drill:
            start_pass = 1
        elif settings.break_pass == -1:
            start_pass = len(depths) if any(h > depths[-1] for h in heights) else 0
        elif settings.break_pass == 0:
            start_pass = 0
        else:
            start_pass = min(int(settings.break_pass), len(depths))
        variants = {False: tuple(geos), True: tuple(split)}
        flipped = {False: False, True: False}

        def pass_geometries(number, remove_last=False):
            nonlocal compensation
            use_split = 0 < start_pass <= number
            current = variants[use_split]
            if remove_last:
                current = current[:-1]
            if not request.drill and not request.closed:
                if flipped[use_split] != (number % 2 == 0):
                    current = reverse_chain(current)
                    flipped[use_split] = not flipped[use_split]
                    if compensation in (41, 42):
                        compensation = 83 - compensation
            variants[use_split] = current
            return current

        safe = settings.workpiece_top + abs(settings.safe_margin)

        def emit_contour(chain, depth):
            for geo in chain:
                geo = geo.resolved
                if geo.kind == "pocket":
                    geo = replace(
                        geo, z_feed=settings.feed_depth,
                        xy_feed=settings.feed_xy, safe_depth=safe, depth=depth,
                        retract_depth=settings.retract_depth)
                    output.geometry(geo)
                else:
                    output.cut_geometry(geo, drill=request.drill)

        output.geometry(request.prepared_path[0].resolved, role="approach")
        output.add("pre_cut")
        index = request.lead_nominal_index
        g40_lead, nominal_lead = request.lead_in[:index], request.lead_in[index:]
        if not request.drill and compensation != 40 and caps.compensation_outside_piece:
            output.add("feed", settings.feed_xy)
            for geo in g40_lead:
                output.geometry(geo, role="lead_in")
        output.add("rapid_z", safe, role="approach")
        output.add("feed", settings.feed_depth)
        output.add("drill" if request.drill else "linear_z", depths[0], role="plunge")
        last_geos = ()
        if not request.drill:
            output.add("feed", settings.feed_xy)
            if compensation != 40 and not caps.compensation_outside_piece:
                for geo in g40_lead:
                    output.geometry(geo, role="lead_in")
            elif software_comp:
                for geo in request.lead_in:
                    output.cut_geometry(geo, role="lead_in")
            if compensation != 40:
                output.add("compensation_on", compensation)
            for geo in nominal_lead:
                output.geometry(geo, role="lead_in")
            last_geos = pass_geometries(1)
            emit_contour(last_geos, depths[0])
            if compensation != 40 and caps.cancel_compensation_for_depth:
                output.add("compensation_off")

        for number, depth in enumerate(depths[1:], start=2):
            current = pass_geometries(
                number, depth == settings.final_depth and request.pocket)
            if request.drill:
                output.add("drill_retract", safe, role="drill")
                output.add("drill", depth, role="drill")
                continue
            last_geos = current
            output.add("feed", settings.feed_depth)
            output.add("linear_z", depth, role="plunge")
            output.add("feed", settings.feed_xy)
            if compensation != 40:
                if not request.closed and not caps.cancel_compensation_for_depth:
                    output.add("compensation_off")
                    output.add("compensation_on", compensation)
                if caps.cancel_compensation_for_depth:
                    output.add("compensation_on", compensation)
            emit_contour(current, depth)
            if compensation != 40 and caps.cancel_compensation_for_depth:
                # Existing profiles receive both cancellations between passes.
                output.add("compensation_off")
                output.add("compensation_off")

        if (last_geos and settings.machine_type != "lathe" and
                (settings.lead_out_mode != "off" or settings.overcut_enabled)):
            if compensation in (41, 42):
                side = 1 if compensation == 41 else -1
            else:
                side = settings.lead_side
                if (not request.closed and
                        len(calculate_depth_passes(
                            settings.workpiece_top, settings.slice_depth,
                            settings.final_depth)) % 2 == 0):
                    side = -side
            machine_comp = (request.compensation in (41, 42) and
                            settings.machine_compensation)
            exit_geos, message = self._exit_geometry(
                last_geos, side, machine_comp, settings, request.closed)
            if message:
                diagnostics.append(diagnostic(
                    request, "lead.invalid_exit",
                    EXIT_ERROR,
                    request.shape_number, message))
                return ToolpathPlanningResult(None, tuple(diagnostics))
            for geo in exit_geos:
                output.cut_geometry(geo, role="lead_out")
        output.add("feed", settings.feed_depth)
        output.add("linear_z", safe, role="retract")
        output.add("rapid_z", settings.retract_depth, role="retract")
        if compensation != 40 and not caps.cancel_compensation_for_depth:
            output.add("compensation_off")
        output.add("post_cut")
        return ToolpathPlanningResult(output.finish(), tuple(diagnostics))
