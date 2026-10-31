"""Small projections of semantic toolpath plans for presentation layers."""

from math import atan2, ceil, cos, pi, sin


def _move_segments(move):
    if move.kind != "arc" or move.center_xy is None:
        return ((move.start_xy, move.end_xy),)
    cx, cy = move.center_xy
    sx, sy = move.start_xy
    radius = ((sx - cx) ** 2 + (sy - cy) ** 2) ** 0.5
    start_angle = atan2(sy - cy, sx - cx)
    count = max(1, int(ceil(abs(move.sweep) / (pi / 36.0))))
    points = [move.start_xy]
    for index in range(1, count):
        angle = start_angle + move.sweep * index / count
        points.append((cx + radius * cos(angle), cy + radius * sin(angle)))
    points.append(move.end_xy)
    return tuple(zip(points, points[1:]))


def plan_xy_segments(plan):
    """Return the XY contour once, even when the plan has several depth passes."""
    if not plan.passes:
        return ()
    seen = set()
    segments = []
    for toolpath_pass in plan.passes:
        for move in toolpath_pass.moves:
            for segment in _move_segments(move):
                if segment not in seen:
                    seen.add(segment)
                    segments.append(segment)
    return tuple(segments)


def plan_xyz_segments(plan):
    """Project plan XY moves at the top surface and at each cutting depth."""
    segments = []

    def add_pass_moves(toolpath_pass, depth):
        for move in toolpath_pass.moves:
            for start_xy, end_xy in _move_segments(move):
                start = (start_xy[0], start_xy[1], depth)
                end = (end_xy[0], end_xy[1], depth)
                segments.append((start, end))

    if plan.passes:
        add_pass_moves(plan.passes[0], plan.workpiece_top)
        for toolpath_pass in plan.passes:
            add_pass_moves(toolpath_pass, toolpath_pass.depth)
    return tuple(segments)
