"""Codec for the existing, versioned ``.d2g`` assignment format.

The legacy Project facade applies the decoded values to current application
objects. This module only validates and decodes the persisted representation.
"""

import ast
import re
from dataclasses import dataclass

from dxf2gcode.application.exceptions import VersionMismatchError


D2G_HEADER = "# +~+~+~ DXF2GCODE project file V%s ~+~+~+"
SUPPORTED_D2G_VERSIONS = (1.1, 1.2, 1.3)
CURRENT_D2G_VERSION = SUPPORTED_D2G_VERSIONS[-1]

_ALLOWED_D2G_ATTRS = frozenset([
    "file", "point_tol", "fitting_tol",
    "scale", "rot",
    "wpzero_x", "wpzero_y",
    "mirrorx", "mirrory",
    "split_lines", "aut_cut_com", "machine_type", "layers",
])


@dataclass(frozen=True)
class LegacyProjectDocument:
    version: float
    values: dict


def decode_d2g(content):
    """Decode a legacy project string without executing its contents."""
    header_pattern = D2G_HEADER.replace("+", r"\+") % r"(\d+\.\d+)"
    match = re.match(header_pattern, content)
    if not match:
        raise Exception("Incorrect project file")

    version = float(match.groups()[0])
    if version not in SUPPORTED_D2G_VERSIONS:
        raise VersionMismatchError(match.group(), CURRENT_D2G_VERSION)

    tree = ast.parse(content)
    values = {}
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
            if len(targets) != 1 or not isinstance(targets[0], ast.Attribute):
                raise ValueError(
                    "Line {}: Only 'd2g.<attr> = <value>' assignments allowed"
                    .format(node.lineno))
            attr_node = targets[0]
            if not (isinstance(attr_node.value, ast.Name)
                    and attr_node.value.id == "d2g"):
                raise ValueError(
                    "Line {}: Target must be 'd2g', got {}"
                    .format(node.lineno, ast.dump(attr_node)))
            attr_name = attr_node.attr
            if attr_name not in _ALLOWED_D2G_ATTRS:
                raise ValueError(
                    "Line {}: Unknown/dangerous attribute '{}'"
                    .format(node.lineno, attr_name))
            values[attr_name] = ast.literal_eval(node.value)
        elif isinstance(node, ast.Expr):
            # Match the legacy reader: standalone expressions are ignored.
            pass
        else:
            raise ValueError(
                "Line {}: Unexpected statement '{}'"
                .format(node.lineno, type(node).__name__))

    return LegacyProjectDocument(version=version, values=values)

