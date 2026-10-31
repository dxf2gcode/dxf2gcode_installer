# -*- coding: utf-8 -*-
"""
State logic for the numeric parameter fields of the mill settings frame.

The fields always show the value(s) of the currently selected shapes. A
parameter can be in one of these states:

``empty``       nothing selected / no shape supports the parameter
``same``        all selected shapes have the same value (may be their default)
``mixed``       the selected shapes have different values
``unavailable`` only a part of the selection supports the parameter

``mixed`` is an indication for the user only. The placeholder text that is
displayed for it must never be written back into a shape (the widgets use a
text that does not parse as a number, see TreeHandler).

A value is marked as a "standard value" when it equals the default the shape
would get: the global configuration value or - for tool derived parameters such
as the additional offset - the tool default of the shape's own layer. The
default is therefore evaluated per shape: shapes can use different tools and
thus different defaults.
"""
from __future__ import absolute_import

# states
EMPTY = "empty"
SAME = "same"
MIXED = "mixed"
UNAVAILABLE = "unavailable"


def values_of(shapes, attribute):
    """Values of ``attribute`` for all shapes that provide it.

    @return (values, missing): the value list and the number of shapes that do
            not provide the parameter at all.
    """
    values = []
    missing = 0
    for shape in shapes:
        try:
            values.append(getattr(shape, attribute))
        except AttributeError:
            missing += 1
    return values, missing


def parameter_state(shapes, attribute):
    """State of one parameter for the given selection.

    @param shapes: the selected shapes (iterable, may be empty)
    @param attribute: name of the shape attribute
    @return (state, value): state is one of EMPTY, SAME, MIXED, UNAVAILABLE.
            The value is only set for the state SAME (None otherwise).
    """
    shapes = list(shapes)
    if not shapes:
        return (EMPTY, None)
    values, missing = values_of(shapes, attribute)
    if missing and values:
        # the parameter is only available for a part of the selection: never
        # silently apply a value to the shapes that do not support it
        return (UNAVAILABLE, None)
    if missing or not values:
        return (EMPTY, None)
    first = values[0]
    for value in values[1:]:
        if value != first:
            return (MIXED, None)
    return (SAME, first)


def is_standard_value(shapes, attribute, default_getter):
    """True when every selected shape uses its own default for the parameter.

    @param shapes: the selected shapes
    @param attribute: name of the shape attribute
    @param default_getter: callable(shape) -> the default value that applies to
            that shape (global configuration or its own tool default)
    @return True when all shapes support the parameter and each one already has
            its default value. A parameter that is unavailable for a part of
            the selection is never reported as a standard value.
    """
    shapes = list(shapes)
    if not shapes:
        return False
    for shape in shapes:
        try:
            value = getattr(shape, attribute)
        except AttributeError:
            return False
        try:
            default = default_getter(shape)
        except Exception:
            return False
        if value != default:
            return False
    return True
