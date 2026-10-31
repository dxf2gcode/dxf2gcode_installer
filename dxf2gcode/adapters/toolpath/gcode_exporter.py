"""Serialize semantic toolpath actions through the selected machine profile."""

from dxf2gcode.domain.geometry.point import Point


class ToolpathGCodeExporter:
    """Format prepared movements; no geometry or pass planning happens here."""

    def export(self, plan, postprocessor):
        output = []
        for action in plan.actions:
            kind, args = action.kind, action.args
            if kind == "literal":
                text = args[0]
            elif kind == "rapid_xy":
                text = postprocessor.rap_pos_xy(Point(*args[0]))
            elif kind == "rapid_z":
                text = postprocessor.rap_pos_z(args[0])
            elif kind == "linear_z":
                text = postprocessor.lin_pol_z(args[0])
            elif kind == "linear_xy":
                text = postprocessor.lin_pol_xy(Point(*args[0]), Point(*args[1]))
            elif kind == "arc":
                direction, start, end, sa, ea, radius, center, ij, sweep = args
                text = postprocessor.lin_pol_arc(
                    direction, Point(*start), Point(*end), sa, ea, radius,
                    Point(*center), Point(*ij), sweep)
            elif kind == "feed":
                text = postprocessor.chg_feed_rate(args[0])
            elif kind == "compensation_on":
                text = postprocessor.set_cut_cor(args[0])
            elif kind == "compensation_off":
                text = postprocessor.deactivate_cut_cor()
            elif kind == "drill":
                text = postprocessor.lin_pol_drill(args[0])
            elif kind == "drill_retract":
                text = postprocessor.lin_ret_drill(args[0])
            elif kind == "pre_cut":
                text = postprocessor.write_pre_shape_cut()
            elif kind == "post_cut":
                text = postprocessor.write_post_shape_cut()
            elif kind == "hole_marker":
                text = postprocessor.make_print_str("(Drilled hole)%nl")
            else:
                raise ValueError("unsupported toolpath action: %s" % kind)
            output.append(text)
        return "".join(output)
