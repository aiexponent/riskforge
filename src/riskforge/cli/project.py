"""CLI plumbing shared by commands.

Storage and engines are imported inside functions so `riskforge --version` and `--help`
start without loading them (ADR-02).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from riskforge.cli.errors import fail

if TYPE_CHECKING:
    from riskforge.storage.filesystem import FileStore


def open_project(project_dir: Path) -> FileStore:
    """The project's store, or exit 3 when the directory holds no project."""
    from riskforge.storage.errors import ProjectNotFoundError
    from riskforge.storage.filesystem import FileStore

    store = FileStore(project_dir)
    try:
        store.ensure_project()
    except ProjectNotFoundError as exc:
        fail(f"{exc} Run `riskforge init` there first, or pass --project-dir.")
    return store
