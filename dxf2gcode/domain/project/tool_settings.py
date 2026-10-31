"""Effective tool values for a shape, with layer defaults."""

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class ToolSettings:
    tool_nr: int
    tool_diameter: float
    speed: float
    start_radius: float
    lead_radius: float
    lead_length: float
    overcut_length: float

    @classmethod
    def from_profile(cls, number, profile):
        return cls(int(number), profile["diameter"], profile["speed"],
                   profile["start_radius"], profile["lead_radius"],
                   profile["lead_length"], profile["overcut_length"])

    def getToolRadius(self):
        return self.tool_diameter / 2.0

    def scaled(self, factor):
        return replace(self, **{
            key: getattr(self, key) * factor
            for key in ("tool_diameter", "start_radius", "lead_radius",
                        "lead_length", "overcut_length")})


def effective_tool(shape, default=None):
    """Return an explicit shape tool or the unchanged layer tool defaults."""
    override = getattr(shape, "tool_override", None)
    if override is not None:
        return override
    return getattr(shape, "parentLayer", default) or default
