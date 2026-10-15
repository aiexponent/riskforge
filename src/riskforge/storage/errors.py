"""Typed storage errors. Each subclasses the built-in error older callers already catch."""

from __future__ import annotations


class ProjectNotFoundError(FileNotFoundError):
    """No RiskForge project in the given directory."""


class ProjectExistsError(FileExistsError):
    """A RiskForge project already exists in the given directory."""


class ManifestMissingError(ProjectNotFoundError, ProjectExistsError):
    """``.riskforge/`` holds a project's data but ``riskforge.yaml`` is gone.

    Both kinds: commands that open the project cannot use it, and ``init`` must not
    start a new project over it.
    """


class SystemNotFoundError(FileNotFoundError):
    """No AI system with the given id in this project."""


class RegisterNotFoundError(FileNotFoundError):
    """The AI system exists but has no risk register yet."""


class InvalidSystemIdError(ValueError):
    """A system id that would point outside the project's systems/ directory."""


class AuditLogCorruptError(ValueError):
    """The audit log holds a line that is not a valid audit entry."""


class ProjectLockedError(TimeoutError):
    """Another process held the project's write lock for longer than the wait allowed."""


class StoredFileCorruptError(ValueError):
    """A stored YAML or JSON file (register, system record, head file) does not parse."""


class PendingChangeError(RuntimeError):
    """A read-only store found a change that a writer has not finished."""
