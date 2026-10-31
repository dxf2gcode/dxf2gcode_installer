"""Construct application services from concrete runtime adapters."""

from dxf2gcode.adapters.project.legacy_repository import (
    LegacyProjectRepository)
from dxf2gcode.application.context import ApplicationContext


def create_application_context(config, logger, quiet=False):
    """Build the shared context used by GUI and command-line workflows."""
    return ApplicationContext(
        config=config,
        logger=logger,
        quiet=quiet,
        project_repository=LegacyProjectRepository(),
    )
