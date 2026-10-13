"""Typed storage errors. Each subclasses the built-in error older callers already catch."""

from __future__ import annotations


class ProjectNotFoundError(FileNotFoundError):
    """No RiskForge project in the given directory."""


class ProjectExistsError(FileExistsError):
    """A RiskForge project already exists in the given directory."""


class SystemNotFoundError(FileNotFoundError):
    """No AI system with the given id in this project."""


class RegisterNotFoundError(FileNotFoundError):
    """The AI system exists but has no risk register yet."""


class InvalidSystemIdError(ValueError):
    """A system id that would point outside the project's systems/ directory."""
