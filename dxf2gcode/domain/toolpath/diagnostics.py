"""Build translatable planning diagnostics without a presentation dependency."""

from dxf2gcode.domain.toolpath.plan import ToolpathDiagnostic


def QT_TRANSLATE_NOOP(context, text):
    """Mark source messages for pylupdate without importing or executing Qt."""
    return text


START_ERROR = QT_TRANSLATE_NOOP("Shape", "Shape %i: %s")
EXIT_ERROR = QT_TRANSLATE_NOOP("Shape", "Shape %i: %s The shape is NOT milled!")
ZERO_SLICE = QT_TRANSLATE_NOOP("Shape", "Shape %i: Z infeed depth is null!")
INVERTED_RANGE = QT_TRANSLATE_NOOP(
    "Shape", "Workpiece Top Z (%f0.2) is lower than end mill depth (%f0.2)")
INITIAL_DEPTH = QT_TRANSLATE_NOOP(
    "Shape", "Initial mill depth (%f0.2) is lower than end mill depth (%f0.2)")
MISSING_LEAD = QT_TRANSLATE_NOOP(
    "Shape", "Shape %i: the lead in mode 'off' is not possible "
    "with G41/G42: the machine can only build the tool "
    "radius compensation with a movement in the XY plane "
    "- the shape is NOT milled! Use the lead in mode "
    "'startmove', 'straight' or 'radius'.")


def diagnostic(request, code, source, *args, severity="error"):
    return ToolpathDiagnostic(
        code=code, severity=severity,
        message=source % args if args else source,
        shape_number=request.shape_number,
        source_message=source, message_args=tuple(args))
