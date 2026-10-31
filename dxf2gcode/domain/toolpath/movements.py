"""Expand prepared geometry into semantic movements without an exporter."""

from math import asin, pi, sqrt

from dxf2gcode.domain.toolpath.plan import (
    ToolpathAction, ToolpathMove, ToolpathPass, ToolpathPlan)


class MovementPlan:
    """Accumulate an ordered plan and the state required by tab transitions."""

    def __init__(self, request):
        self.request = request
        self.actions = []
        self.feed = request.initial_state.feed
        self.z_word = request.initial_state.z_word
        self.last_z = request.initial_state.last_absolute_z

    def add(self, kind, *args, role="cut"):
        self.actions.append(ToolpathAction(kind, tuple(args), role))
        if kind == "feed":
            self.feed = args[0]
        elif kind in ("rapid_z", "linear_z", "drill", "drill_retract"):
            z = args[0]
            if self.request.capabilities.absolute_coordinates:
                self.z_word = z
            else:
                self.z_word = z - self.last_z
                self.last_z = z

    def geometry(self, geo, role="cut"):
        if geo.kind == "rapid":
            self.add("rapid_xy", geo.end, role=role)
        elif geo.kind == "hole":
            self.add("hole_marker", role=role)
        elif geo.kind == "pocket":
            self.add("feed", geo.z_feed, role="pocket")
            self.add("linear_z", geo.safe_depth, role="pocket")
            self.add("rapid_z", geo.retract_depth, role="pocket")
            self.add("rapid_xy", geo.end, role="pocket")
            self.add("rapid_z", geo.safe_depth, role="pocket")
            self.add("feed", geo.z_feed, role="pocket")
            self.add("linear_z", geo.depth, role="pocket")
            self.add("feed", geo.xy_feed, role="pocket")
        elif geo.kind == "break":
            old_z, old_feed = self.z_word, self.feed
            if geo.height <= old_z:
                self.add("linear_xy", geo.start, geo.end, role="tab")
                return
            self.add("feed", geo.z_feed, role="tab")
            self.add("linear_z", geo.height, role="tab")
            self.add("feed", geo.xy_feed, role="tab")
            self.add("linear_xy", geo.start, geo.end, role="tab")
            self.add("feed", geo.z_feed, role="tab")
            self.add("linear_z", old_z, role="tab")
            self.add("feed", old_feed, role="tab")
        elif geo.kind == "arc":
            self._arc(geo, role)
        elif geo.kind == "line":
            self.add("linear_xy", geo.start, geo.end, role=role)
        else:
            raise ValueError("unsupported planning geometry: %s" % geo.kind)

    def cut_geometry(self, geo, drill=False, role="cut"):
        geo = geo.resolved
        if geo.kind == "pocket":
            self.geometry(geo, role)
            return
        if drill:
            self.add("hole_marker", role="drill")
            return
        decimals = self.request.capabilities.post_decimals
        if (geo.kind == "hole" or
                round(geo.start[0], decimals) != round(geo.end[0], decimals) or
                round(geo.start[1], decimals) != round(geo.end[1], decimals) or
                (geo.kind == "arc" and
                 geo.length > 0.5 * 0.1 ** decimals * pi)):
            self.geometry(geo, role)

    def _arc(self, geo, role):
        caps = self.request.capabilities
        if geo.radius > caps.max_arc_radius:
            self.add("linear_xy", geo.start, geo.end, role=role)
            return
        if caps.arcs_as_lines:
            tolerance = caps.fitting_tolerance
            segment = 2 * sqrt(tolerance * (2 * geo.radius - tolerance))
            alpha = 2 * asin(segment / (2 * geo.radius))
            count = int(abs(geo.sweep // alpha))
            start = geo.start
            for index in range(1, count + 1):
                end = geo.arc_point(geo.start_angle + index * geo.sweep / count)
                self.add("linear_xy", start, end, role=role)
                start = end
            return
        sign = 1 if geo.sweep > 0 else -1
        start_angle = geo.start_angle + pi / 2 * sign
        end_angle = geo.end_angle - pi / 2 * sign
        start, end = geo.start, geo.end
        direction = "ccw" if geo.sweep > 0 else "cw"
        if geo.sweep < 0 and caps.counterclockwise_arcs_only:
            direction = "ccw"
            start, end = end, start
            start_angle, end_angle = end_angle, start_angle
        ij = (geo.center[0] - start[0], geo.center[1] - start[1])
        self.add("arc", direction, start, end, start_angle, end_angle,
                 geo.radius, geo.center, ij, geo.sweep, role=role)

    def finish(self):
        """Project cutting passes from the same ordered action sequence."""
        request, settings = self.request, self.request.settings
        groups = []
        depth = settings.workpiece_top
        approach = (0.0, 0.0)
        for action in self.actions:
            if action.kind == "rapid_xy":
                approach = action.args[0]
            elif action.kind in ("linear_z", "drill"):
                depth = action.args[0]
            elif action.kind in ("linear_xy", "arc"):
                if action.kind == "linear_xy":
                    move = ToolpathMove("linear_xy", *action.args)
                else:
                    args = action.args
                    move = ToolpathMove("arc", args[1], args[2], args[6], args[8])
                if not groups or groups[-1][0] != depth:
                    groups.append((depth, []))
                groups[-1][1].append(move)
        passes = tuple(
            ToolpathPass(index + 1, depth, tuple(moves))
            for index, (depth, moves) in enumerate(groups))
        return ToolpathPlan(
            shape_number=request.shape_number, approach_xy=approach,
            passes=passes, workpiece_top=settings.workpiece_top,
            safe_margin=settings.safe_margin, retract_depth=settings.retract_depth,
            feed_depth=settings.feed_depth, feed_xy=settings.feed_xy,
            actions=tuple(self.actions))
