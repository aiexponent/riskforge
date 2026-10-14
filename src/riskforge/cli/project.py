"""CLI plumbing shared by commands.

Storage and engines are imported inside functions so `riskforge --version` and `--help`
start without loading them (ADR-02).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

import typer

from riskforge.cli.errors import EXIT_TAMPERED, err_console, fail

T = TypeVar("T")

if TYPE_CHECKING:
    from riskforge.engine.integrity import IntegrityReport
    from riskforge.models.register import RiskRegister
    from riskforge.models.risk import RiskDimension
    from riskforge.models.system import AISystem, AnnexIIICategory
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


def open_project_for_reading(project_dir: Path) -> FileStore:
    """The project's store opened read-only: no lock, no recovery, no file written.

    ``riskforge verify`` uses it so a read-only copy or an archive mount can be checked.
    Exits 3 when the directory holds no project.
    """
    from riskforge.storage.filesystem import FileStore

    open_project(project_dir)
    return FileStore(project_dir, read_only=True)


def print_integrity_failure(report: IntegrityReport) -> None:
    """Print each finding of a failed integrity check on its own line, to stderr."""
    from rich.markup import escape

    count = len(report.errors)
    err_console.print(
        f"[red]✗[/red] Integrity check failed with {count} finding{'s' if count != 1 else ''}:",
        highlight=False,
    )
    for error in report.errors:
        err_console.print(f"  [red]•[/red] {escape(error)}", highlight=False, soft_wrap=True)


def print_integrity_warnings(report: IntegrityReport) -> None:
    from rich.markup import escape

    for warning in report.warnings:
        err_console.print(f"[yellow]![/yellow] {escape(warning)}", highlight=False, soft_wrap=True)


@contextlib.asynccontextmanager
async def preflight(store: FileStore) -> AsyncIterator[IntegrityReport | None]:
    """Hold the project's unit of work, and refuse with exit 2 unless the project is intact.

    The check runs after the unit of work has taken the lock and finished or discarded
    any interrupted change, and the lock is held until the block ends, so nothing can
    change between the check and the command's own change. Warnings are printed. An
    ``IntegrityError`` from the check, or from an engine inside the block, prints one
    line per finding and exits 2; nothing was written.
    """
    from riskforge.engine.integrity import IntegrityError, checked_unit_of_work

    try:
        async with checked_unit_of_work(store) as report:
            if report is not None:
                print_integrity_warnings(report)
            yield report
    except IntegrityError as exc:
        print_integrity_failure(exc.report)
        err_console.print(
            "Nothing was changed. Run `riskforge verify` for the full report.", highlight=False
        )
        raise typer.Exit(EXIT_TAMPERED) from None


def run_checked(project_dir: Path, body: Callable[[FileStore], Awaitable[T]]) -> T:
    """Open the project and run ``body`` inside ``preflight``, in one event loop."""
    store = open_project(project_dir)

    async def _main() -> T:
        async with preflight(store):
            return await body(store)

    return asyncio.run(_main())


async def read_system_or_fail(store: FileStore, system_id: str) -> AISystem:
    """The stored system, or exit 3 naming the systems this project does have."""
    from riskforge.storage.errors import InvalidSystemIdError, SystemNotFoundError

    try:
        return await store.read_system(system_id)
    except SystemNotFoundError:
        known = await store.list_systems()
        fail(f"No system '{system_id}' in this project. Systems: {', '.join(known) or 'none'}.")
    except InvalidSystemIdError as exc:
        fail(str(exc))


async def read_register_or_fail(store: FileStore, system_id: str) -> RiskRegister:
    """The system's register, or exit 3 when the system or its register is missing."""
    from riskforge.storage.errors import RegisterNotFoundError

    await read_system_or_fail(store, system_id)
    try:
        return await store.read_register(system_id)
    except RegisterNotFoundError:
        fail(
            f"System {system_id} has no risk register yet. "
            f"Run `riskforge assess {system_id} -a NAME -r ROLE` first."
        )


def parse_category(
    value: str | None, param: str = "'--category' / '-c'"
) -> AnnexIIICategory | None:
    """The Annex III category named by *value*; a bad value is a usage error (exit 3)."""
    from riskforge.models.system import AnnexIIICategory

    if value is None:
        return None
    try:
        return AnnexIIICategory(value)
    except ValueError:
        valid = ", ".join(c.value for c in AnnexIIICategory)
        raise typer.BadParameter(
            f"'{value}' is not an Annex III category. Use one of: {valid}.", param_hint=param
        ) from None


def parse_dimension(value: str | None, param: str = "'--dimension'") -> RiskDimension | None:
    """The risk dimension named by *value*; a bad value is a usage error (exit 3)."""
    from riskforge.models.risk import RiskDimension

    if value is None:
        return None
    try:
        return RiskDimension(value)
    except ValueError:
        valid = ", ".join(d.value for d in RiskDimension)
        raise typer.BadParameter(
            f"'{value}' is not a risk dimension. Use one of: {valid}.", param_hint=param
        ) from None
