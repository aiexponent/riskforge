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
    from riskforge.engine.integrity import IntegrityError, IntegrityReport
    from riskforge.integrity.signing import Ed25519Signer
    from riskforge.models.register import RiskRegister
    from riskforge.models.risk import RiskDimension
    from riskforge.models.system import AISystem, AnnexIIICategory
    from riskforge.storage.filesystem import FileStore


MANIFEST_MISSING_HINT = "Restore riskforge.yaml from a backup, or use another --project-dir."


def open_project(project_dir: Path) -> FileStore:
    """The project's store, or exit 3 when the directory holds no project."""
    from riskforge.storage.errors import ManifestMissingError, ProjectNotFoundError
    from riskforge.storage.filesystem import FileStore

    store = FileStore(project_dir)
    try:
        store.ensure_project()
    except ManifestMissingError as exc:
        fail(f"{exc} {MANIFEST_MISSING_HINT}")
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


def print_refusal(exc: IntegrityError) -> None:
    """Print a refused change: one line per finding, then what was and was not changed."""
    print_integrity_failure(exc.report)
    if exc.recovered:
        closing = (
            "An unfinished earlier change (.riskforge/txn.json) was finished or discarded "
            "before the check; this command changed nothing else."
        )
    else:
        closing = "Nothing was changed."
    err_console.print(
        f"{closing} Run `riskforge verify` for the full report.", highlight=False, soft_wrap=True
    )


def print_integrity_warnings(report: IntegrityReport) -> None:
    from rich.markup import escape

    for warning in report.warnings:
        err_console.print(f"[yellow]![/yellow] {escape(warning)}", highlight=False, soft_wrap=True)


@contextlib.asynccontextmanager
async def preflight(store: FileStore) -> AsyncIterator[IntegrityReport | None]:
    """Hold the project's unit of work, and refuse with exit 2 unless the project is intact.

    The check runs after the unit of work has taken the lock and finished or discarded
    any interrupted change, and the lock is held until the block ends, so no other
    RiskForge command can write in between. A file changed outside RiskForge after the
    check is detected when the command reads it or records its entry. Warnings are
    printed. An ``IntegrityError`` from the check, or from an engine inside the block,
    prints one line per finding and exits 2; the command wrote nothing.
    """
    from riskforge.engine.integrity import IntegrityError, checked_unit_of_work

    try:
        async with checked_unit_of_work(store) as report:
            if report is not None:
                print_integrity_warnings(report)
            yield report
    except IntegrityError as exc:
        print_refusal(exc)
        raise typer.Exit(EXIT_TAMPERED) from None


def run_checked(project_dir: Path, body: Callable[[FileStore], Awaitable[T]]) -> T:
    """Open the project and run ``body`` inside ``preflight``, in one event loop."""
    store = open_project(project_dir)

    async def _main() -> T:
        async with preflight(store):
            return await body(store)

    return asyncio.run(_main())


def run_read_checked(project_dir: Path, body: Callable[[FileStore], Awaitable[T]]) -> T:
    """Run ``body`` on the project opened read-only, after the check ``verify`` runs.

    For commands that only read: no lock is taken and nothing is written, so they work
    on a read-only copy. A change in progress exits 1, a failed check prints one line
    per finding and exits 2, as ``riskforge verify`` does. A register or system file
    that ``body`` reads and that changed after the check also exits 2.
    """
    from riskforge.cli.errors import EXIT_FAILED
    from riskforge.engine.integrity import (
        ChangeInProgressError,
        IntegrityError,
        check_integrity_settled,
        reads_checked_against,
    )

    store = open_project_for_reading(project_dir)

    async def _main() -> T:
        try:
            report = await check_integrity_settled(store)
        except ChangeInProgressError as exc:
            fail(str(exc), EXIT_FAILED)
        print_integrity_warnings(report)
        if not report.ok:
            print_integrity_failure(report)
            err_console.print(
                "Nothing was changed. Run `riskforge verify` for the full report.",
                highlight=False,
            )
            raise typer.Exit(EXIT_TAMPERED)
        try:
            with reads_checked_against(store, report):
                return await body(store)
        except IntegrityError as exc:
            print_refusal(exc)
            raise typer.Exit(EXIT_TAMPERED) from None

    return asyncio.run(_main())


async def read_system_or_fail(store: FileStore, system_id: str) -> AISystem:
    """The stored system, or exit 3 naming the systems this project does have.

    Inside ``preflight`` the read is compared with what the check saw
    (``IntegrityError`` when the file changed since).
    """
    from riskforge.engine.integrity import read_system_checked
    from riskforge.storage.errors import InvalidSystemIdError, SystemNotFoundError

    try:
        return await read_system_checked(store, system_id)
    except SystemNotFoundError:
        known = await store.list_systems()
        fail(f"No system '{system_id}' in this project. Systems: {', '.join(known) or 'none'}.")
    except InvalidSystemIdError as exc:
        fail(str(exc))


async def read_register_or_fail(store: FileStore, system_id: str) -> RiskRegister:
    """The system's register, or exit 3 when the system or its register is missing.

    Inside ``preflight`` the read is compared with what the check saw
    (``IntegrityError`` when the file changed since).
    """
    from riskforge.engine.integrity import read_register_checked
    from riskforge.storage.errors import RegisterNotFoundError

    await read_system_or_fail(store, system_id)
    try:
        return await read_register_checked(store, system_id)
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


def load_signer(path: Path) -> Ed25519Signer:
    """Load a private key for signing, or exit 3.

    Exits 3 when the file is missing, unreadable, not a regular file or not an Ed25519
    private key, and on POSIX systems when it is a symbolic link or its group or other
    users have any access to it.
    """
    import errno
    import os
    import stat

    from riskforge.integrity.signing import Ed25519Signer, KeyFileError

    # One open: the mode check and the read use the same descriptor, so the file cannot be
    # swapped in between. O_NOFOLLOW refuses a symlink; O_NONBLOCK keeps a FIFO from
    # blocking the open (the regular-file check then rejects it).
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_BINARY", 0)
    )
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        fail(
            f"Key file not found: {path}. RiskForge signs with an Ed25519 key file; "
            "create one with `riskforge keygen --output FILE`."
        )
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EMLINK) and path.is_symlink():
            fail(f"Key file {path} is a symbolic link. Pass the path of the key file itself.")
        fail(f"Cannot read key file {path}: {exc.strerror or exc}")
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            fail(f"Key file {path} is not a regular file.")
        mode = stat.S_IMODE(info.st_mode)
        if os.name == "posix" and mode & 0o077:
            fail(
                f"Key file {path} can be read by other users (mode {mode:03o}). "
                f"Run: chmod 600 {path}"
            )
        with os.fdopen(fd, "rb", closefd=False) as fh:
            pem = fh.read()
    except OSError as exc:
        fail(f"Cannot read key file {path}: {exc.strerror or exc}")
    finally:
        os.close(fd)
    try:
        return Ed25519Signer.from_pem(pem, path)
    except KeyFileError as exc:
        fail(str(exc))


def load_trusted_keys(paths: list[Path]) -> list[str]:
    """Base64 raw public keys from PEM public key files, or exit 3 on the first bad file."""
    from riskforge.integrity.signing import KeyFileError, load_public_key_b64

    keys: list[str] = []
    for path in paths:
        try:
            keys.append(load_public_key_b64(path))
        except KeyFileError as exc:
            fail(str(exc))
    return keys
