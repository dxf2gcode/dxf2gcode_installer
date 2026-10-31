"""Explicit application-scoped dependencies for migrated use cases."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ApplicationContext:
    """Runtime dependencies supplied by the GUI or CLI composition root."""

    config: object
    logger: object
    quiet: bool = False
    project_repository: object = None

