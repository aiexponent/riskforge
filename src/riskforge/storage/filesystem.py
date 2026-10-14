"""FileStore: OSS storage backend using YAML + JSONL files.

All data is persisted under ``<project_dir>/.riskforge/`` using a combination
of YAML files (human-readable, diffable) and JSONL for the append-only audit
log.

Directory layout
----------------
::

    <project_dir>/
    ├── riskforge.yaml          chmod 600  # project manifest
    └── .riskforge/             chmod 700
        ├── audit.jsonl         chmod 600  # append-only audit chain
        ├── audit.head.json                # seq and hash of the last entry written
        ├── audit.lock                     # serialises writers across processes
        ├── txn.json                       # journal, only while a commit is in flight
        ├── .nodelete                      # sentinel preventing accidental deletion
        └── systems/
            └── <system_id>/
                ├── system.yaml
                ├── register.yaml
                └── mitigations.yaml       # derived catalogue, never read back

Writes
------
Every file is replaced atomically (temp file, fsync, rename), so a reader sees
the old file or the new one, never a mix. Inside ``unit_of_work()``, register
and system writes are staged as ``<name>.pending`` and renamed into place only
after the audit entry that records them is appended. A journal (``txn.json``)
written before the append records the log length, so the next unit of work can
finish a change whose entry reached the log in full, or cut off a torn append and
discard the change.

Security model
--------------
- The ``.riskforge`` directory and all files within it are created with
  restrictive permissions (700 / 600) to prevent other local users from
  reading sensitive risk data.
- A ``.nodelete`` sentinel file inside ``.riskforge/`` guards against
  accidental ``rm -rf`` of the project root.
- If the project root is inside a git repository and ``riskforge.yaml``
  would be tracked, a warning is emitted; callers should add
  ``.riskforge/`` to ``.gitignore``.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import errno
import hashlib
import json
import logging
import os
import stat
import subprocess
import tempfile
import warnings
from collections.abc import AsyncIterator
from pathlib import Path

import yaml
from filelock import FileLock, Timeout

from riskforge.models.audit import AuditEntry
from riskforge.models.register import RiskRegister
from riskforge.models.system import AISystem
from riskforge.storage.base import StorageBackend
from riskforge.storage.errors import (
    AuditLogCorruptError,
    InvalidSystemIdError,
    ProjectExistsError,
    ProjectLockedError,
    ProjectNotFoundError,
    RegisterNotFoundError,
    SystemNotFoundError,
)

logger = logging.getLogger(__name__)

SENTINEL = ".nodelete"
PENDING_SUFFIX = ".pending"
DEFAULT_LOCK_TIMEOUT = 120.0
_LOCK_POLL_SECONDS = 0.02


class _Scope:
    """The writes staged by one open unit of work, as paths relative to ``.riskforge``."""

    def __init__(self) -> None:
        self.staged: list[str] = []


# Open units of work in the current context, keyed by the resolved .riskforge path, so
# two FileStore objects for one project join the same scope instead of waiting on each other.
_ACTIVE_UOW: contextvars.ContextVar[dict[str, _Scope] | None] = contextvars.ContextVar(
    "riskforge_filestore_uow", default=None
)


def _fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write(path: Path, data: bytes) -> None:
    """Replace ``path`` with ``data`` so readers see the old or the new file, never a mix."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    _fsync_dir(path.parent)


def _pending(path: Path) -> Path:
    return path.with_name(path.name + PENDING_SUFFIX)


def _first_line(exc: Exception) -> str:
    return str(exc).splitlines()[0] if str(exc) else type(exc).__name__


def _parse_entry(line: bytes | str) -> AuditEntry | None:
    try:
        return AuditEntry.model_validate(json.loads(line))
    except ValueError:  # JSONDecodeError, UnicodeDecodeError and pydantic ValidationError
        return None


def _last_line(path: Path) -> str:
    last = ""
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            stripped = raw.strip()
            if stripped:
                last = stripped
    return last


class FileStore(StorageBackend):
    """Stores project state as YAML + JSONL under ``.riskforge/`` directory.

    This is the OSS default storage backend. State is git-committable,
    human-readable by regulators, and diff-resolvable by compliance teams.

    All blocking I/O is dispatched to a thread pool via
    :func:`asyncio.to_thread` so the implementation is safe inside an
    ``asyncio`` event loop without blocking the main thread.

    Parameters
    ----------
    project_dir:
        The project working directory.  All RiskForge data is stored
        under ``project_dir / ".riskforge"``.
    lock_timeout:
        Seconds ``unit_of_work()`` waits for another process to release the
        project lock before it raises :class:`ProjectLockedError`. Defaults to
        ``DEFAULT_LOCK_TIMEOUT`` (120 s).
    """

    def __init__(self, project_dir: Path, lock_timeout: float | None = None) -> None:
        self._root = project_dir / ".riskforge"
        self._key = os.path.realpath(self._root)
        self._lock_timeout = DEFAULT_LOCK_TIMEOUT if lock_timeout is None else lock_timeout
        self._audit_path = self._root / "audit.jsonl"
        self._head_path = self._root / "audit.head.json"
        self._journal_path = self._root / "txn.json"
        self._lock_path = self._root / "audit.lock"
        self._systems_dir = self._root / "systems"
        self._async_lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------ #
    # Internal sync helpers (called via asyncio.to_thread)                #
    # ------------------------------------------------------------------ #

    def _ensure_dirs(self) -> None:
        """Create the ``.riskforge`` tree with chmod 700; write sentinel. Idempotent."""
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._systems_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self._root, stat.S_IRWXU)
        os.chmod(self._systems_dir, stat.S_IRWXU)
        sentinel = self._root / SENTINEL
        if not sentinel.exists():
            sentinel.write_text(
                "Do not delete this directory. It contains the RiskForge audit log.\n",
                encoding="utf-8",
            )
            os.chmod(sentinel, stat.S_IRUSR | stat.S_IWUSR)

    def _gitignore_check(self) -> None:
        """Warn if ``riskforge.yaml`` in the project root would be git-tracked."""
        manifest = self._root.parent / "riskforge.yaml"
        try:
            result = subprocess.run(
                ["git", "check-ignore", "-q", str(manifest)],
                capture_output=True,
                cwd=self._root.parent,
            )
            # Exit 0 → ignored (good). Exit 1 → not ignored (warn).
            if result.returncode == 1:
                warnings.warn(
                    f"{manifest} is NOT listed in .gitignore. "
                    "Add '.riskforge/' to your .gitignore to avoid "
                    "committing sensitive risk assessment data.",
                    stacklevel=4,
                )
        except (FileNotFoundError, OSError):
            pass  # git not installed or not in a repo

    def _system_dir(self, system_id: str) -> Path:
        # Reject path traversal before system_id reaches the filesystem. Legitimate
        # ids are UUIDs (riskforge init); an id containing a path separator, "..",
        # or a null byte is an attempt to escape the systems/ directory. A benign
        # typo (no separators) still falls through to a clean "not found" error.
        if (
            system_id in ("", ".", "..")
            or "/" in system_id
            or "\\" in system_id
            or "\x00" in system_id
        ):
            raise InvalidSystemIdError(
                f"Invalid system id '{system_id}': must not contain path separators or '..'."
            )
        return self._systems_dir / system_id

    def _relative(self, path: Path) -> str:
        return path.relative_to(self._root).as_posix()

    def _scope(self) -> _Scope | None:
        return (_ACTIVE_UOW.get() or {}).get(self._key)

    def _readable(self, path: Path) -> Path:
        """The file a read should see: this unit of work's staged copy, else the committed one."""
        scope = self._scope()
        if scope is not None and self._relative(path) in scope.staged:
            return _pending(path)
        return path

    def _write(self, path: Path, data: bytes) -> None:
        scope = self._scope()
        if scope is not None:
            _atomic_write(_pending(path), data)
            if self._relative(path) not in scope.staged:
                scope.staged.append(self._relative(path))
        else:
            _atomic_write(path, data)

    def _settle_log(self, journal: dict) -> AuditEntry | None:
        """The entry an interrupted commit appended, or None after removing a torn append.

        The commit appended at most one line, with a single write, at ``log_size``. One
        complete line holding the entry that follows ``after_seq`` means the append
        finished. Bytes without a line end, or one line that is not an entry, are what is
        left of an append that failed part way; they are cut off so the log ends where it
        did before the commit. Anything else (more than one line, or a valid entry with
        another seq) was not written by this commit and is never removed.
        """
        if not self._audit_path.exists():
            return None
        with self._audit_path.open("r+b") as fh:
            fh.seek(0, os.SEEK_END)
            if fh.tell() <= journal["log_size"]:
                return None
            fh.seek(journal["log_size"])
            tail = fh.read()
            complete = tail.endswith(b"\n") and tail.count(b"\n") == 1
            entry = _parse_entry(tail) if complete else None
            if entry is not None and entry.seq == journal["after_seq"] + 1:
                return entry
            if b"\n" in tail[:-1] or entry is not None:
                raise AuditLogCorruptError(
                    "The audit log changed in a way an interrupted RiskForge commit cannot "
                    "explain, so it was left as it is. Run `riskforge verify`."
                )
            fh.truncate(journal["log_size"])
            fh.flush()
            os.fsync(fh.fileno())
        return None

    def _write_head(self, seq: int, entry_hash: str) -> None:
        head = {"seq": seq, "entry_hash": entry_hash}
        _atomic_write(self._head_path, json.dumps(head).encode("utf-8"))

    def _recover(self) -> None:
        """Finish or discard a change that an earlier unit of work left behind.

        The journal names the staged files, the chain head before the append and the
        log length before it. If the appended entry is complete, the staged files are
        renamed into place; otherwise the torn append is cut off and the staged files
        are deleted. Any other pending or temp file is an uncommitted write and is
        deleted, and a system directory left empty by that is removed.
        """
        emptied: set[Path] = set()
        if self._journal_path.exists():
            journal = json.loads(self._journal_path.read_text(encoding="utf-8"))
            appended = self._settle_log(journal)
            for rel in journal["files"]:
                final = self._root / rel
                pending = _pending(final)
                if appended is not None and pending.exists():
                    os.replace(pending, final)
                    _fsync_dir(final.parent)
                elif appended is None:
                    pending.unlink(missing_ok=True)
                    emptied.add(final.parent)
            if appended is not None:
                self._write_head(appended.seq, appended.entry_hash)
            self._journal_path.unlink()
            _fsync_dir(self._root)
        if self._systems_dir.exists():
            leftovers = [
                *self._systems_dir.glob(f"*/*{PENDING_SUFFIX}"),
                *self._systems_dir.glob("*/.*.tmp"),
            ]
            for leftover in leftovers:
                leftover.unlink()
                emptied.add(leftover.parent)
        if self._root.exists():
            for leftover in self._root.glob(".*.tmp"):
                leftover.unlink()
        for directory in emptied:
            if directory.parent == self._systems_dir and directory.is_dir():
                if not any(directory.iterdir()):
                    directory.rmdir()
        scope = self._scope()
        if scope is not None:
            scope.staged.clear()

    # ------------------------------------------------------------------ #
    # Hash computation                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _compute_hash(prev_hash: str, entry: AuditEntry) -> str:
        """Compute SHA-256 over the canonical JSON of *entry* (excluding entry_hash).

        The digest covers ``prev_hash`` plus all entry fields except
        ``entry_hash`` itself, serialised with sorted keys for determinism.

        Parameters
        ----------
        prev_hash:
            ``entry_hash`` of the immediately preceding AuditEntry, or ``""``
            for the genesis entry.
        entry:
            The entry to hash.  Its ``entry_hash`` field is ignored.

        Returns
        -------
        str
            Lowercase hexadecimal SHA-256 digest.
        """
        data = entry.model_dump(mode="json")
        data["entry_hash"] = ""  # canonical: entry_hash="" during hash computation
        canonical = json.dumps(
            {"prev_hash": prev_hash, **data},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------ #
    # Unit of work                                                         #
    # ------------------------------------------------------------------ #

    @contextlib.asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[None]:
        """Hold the project write lock; commit staged writes with the audit entry.

        Re-entrant: a nested call, from this or another FileStore for the same
        project, joins the open scope. On entry, and on exit, the scope finishes or
        discards anything an interrupted commit left behind.

        Raises
        ------
        ProjectLockedError
            If another process holds the project lock for longer than ``lock_timeout``.
        RuntimeError
            If the scope ends without an error but with writes that no audit entry
            recorded. The writes are discarded.
        """
        active = _ACTIVE_UOW.get() or {}
        if self._key in active:
            yield
            return
        loop = asyncio.get_running_loop()
        if self._async_lock is None or self._lock_loop is not loop:
            # CLI commands call asyncio.run more than once on one store, and an
            # asyncio.Lock must not outlive the loop it was first used on.
            self._async_lock = asyncio.Lock()
            self._lock_loop = loop
        async with self._async_lock:
            await asyncio.to_thread(self._ensure_dirs)
            lock = FileLock(str(self._lock_path))
            deadline = loop.time() + self._lock_timeout
            while True:
                try:
                    lock.acquire(timeout=0)
                    break
                except Timeout:
                    if loop.time() >= deadline:
                        raise ProjectLockedError(
                            "Another riskforge process holds the project lock "
                            f"({self._lock_path}); gave up after {self._lock_timeout:g} s. "
                            "Try again when it has finished."
                        ) from None
                    await asyncio.sleep(_LOCK_POLL_SECONDS)
            scope = _Scope()
            token = _ACTIVE_UOW.set({**active, self._key: scope})
            try:
                await asyncio.to_thread(self._recover)
                try:
                    yield
                except BaseException as exc:
                    try:
                        await asyncio.to_thread(self._recover)
                    except Exception as recovery_error:
                        exc.add_note(
                            "Cleaning up the project after this error also failed: "
                            f"{recovery_error!r}. The next RiskForge command retries it."
                        )
                    raise
                unrecorded = list(scope.staged)
                await asyncio.to_thread(self._recover)
                if unrecorded:
                    raise RuntimeError(
                        "A unit of work ended with writes that no audit entry recorded, so "
                        f"they were discarded: {', '.join(unrecorded)}."
                    )
            finally:
                _ACTIVE_UOW.reset(token)
                lock.release()

    # ------------------------------------------------------------------ #
    # Project lifecycle                                                    #
    # ------------------------------------------------------------------ #

    async def init_project(self, project_id: str, metadata: dict) -> None:
        """Initialise the ``.riskforge`` directory for a new project.

        Writes ``riskforge.yaml`` at the project root with chmod 600.

        Raises
        ------
        ProjectExistsError
            If ``riskforge.yaml`` already exists (a ``FileExistsError``).
        """

        def _sync() -> None:
            self._ensure_dirs()
            self._gitignore_check()
            manifest_path = self._root.parent / "riskforge.yaml"
            content = {"project_id": project_id, "schema_version": "1.0.0", **metadata}
            data = yaml.dump(content, sort_keys=False, allow_unicode=True).encode("utf-8")
            try:
                fd = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError as exc:
                raise ProjectExistsError(
                    f"A RiskForge project already exists in {self._root.parent.resolve()} "
                    "(riskforge.yaml found)."
                ) from exc
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            logger.info("Project '%s' initialised at %s", project_id, self._root.parent)

        await asyncio.to_thread(_sync)

    def ensure_project(self) -> None:
        """Raise ProjectNotFoundError unless ``riskforge.yaml`` exists."""
        manifest = self._root.parent / "riskforge.yaml"
        if not manifest.exists():
            raise ProjectNotFoundError(
                f"No RiskForge project in {self._root.parent.resolve()} (riskforge.yaml not found)."
            )

    # ------------------------------------------------------------------ #
    # AI system CRUD                                                       #
    # ------------------------------------------------------------------ #

    async def write_system(self, system_id: str, data: AISystem) -> None:
        """Persist *data* to ``systems/{system_id}/system.yaml`` with chmod 600."""

        def _sync() -> None:
            self._ensure_dirs()
            sdir = self._system_dir(system_id)
            sdir.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(sdir, stat.S_IRWXU)
            payload = yaml.dump(data.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
            self._write(sdir / "system.yaml", payload.encode("utf-8"))
            logger.debug("Wrote system '%s'", system_id)

        await asyncio.to_thread(_sync)

    async def read_system(self, system_id: str) -> AISystem:
        """Read ``systems/{system_id}/system.yaml`` and return an :class:`AISystem`.

        Raises
        ------
        SystemNotFoundError
            If the YAML file does not exist (a ``FileNotFoundError``).
        """

        def _sync() -> AISystem:
            path = self._readable(self._system_dir(system_id) / "system.yaml")
            if not path.exists():
                raise SystemNotFoundError(f"No system '{system_id}' in this project.")
            return AISystem.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

        return await asyncio.to_thread(_sync)

    async def list_systems(self) -> list[str]:
        """Return the sorted ids of systems whose ``system.yaml`` is committed."""

        def _sync() -> list[str]:
            if not self._systems_dir.exists():
                return []
            return sorted(
                entry.name
                for entry in self._systems_dir.iterdir()
                if entry.is_dir() and (entry / "system.yaml").exists()
            )

        return await asyncio.to_thread(_sync)

    # ------------------------------------------------------------------ #
    # Risk register CRUD                                                   #
    # ------------------------------------------------------------------ #

    async def write_register(self, system_id: str, register: RiskRegister) -> None:
        """Persist a :class:`RiskRegister` as two files.

        Writes:
        - ``systems/{system_id}/register.yaml``: register metadata + risk items
        - ``systems/{system_id}/mitigations.yaml``: flat mitigation catalogue
          with back-links to each parent risk item
        """

        def _sync() -> None:
            self._ensure_dirs()
            sdir = self._system_dir(system_id)
            sdir.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(sdir, stat.S_IRWXU)
            reg_dict = register.model_dump(mode="json")
            catalogue = [
                {**mitigation, "_risk_item_id": item["id"]}
                for item in reg_dict.get("items", [])
                for mitigation in item.get("mitigations", [])
            ]
            reg_bytes = yaml.dump(reg_dict, sort_keys=False, allow_unicode=True).encode("utf-8")
            mit_bytes = yaml.dump(
                {"mitigations": catalogue}, sort_keys=False, allow_unicode=True
            ).encode("utf-8")
            self._write(sdir / "register.yaml", reg_bytes)
            self._write(sdir / "mitigations.yaml", mit_bytes)
            logger.debug(
                "Wrote register for system '%s' (%d items, %d mitigations)",
                system_id,
                len(reg_dict.get("items", [])),
                len(catalogue),
            )

        await asyncio.to_thread(_sync)

    async def read_register_document(self, system_id: str) -> dict:
        """Return ``register.yaml`` as stored, as a dict.

        Raises
        ------
        RegisterNotFoundError
            If ``register.yaml`` does not exist for *system_id* (a ``FileNotFoundError``).
        """

        def _sync() -> dict:
            path = self._readable(self._system_dir(system_id) / "register.yaml")
            if not path.exists():
                raise RegisterNotFoundError(f"System '{system_id}' has no risk register yet.")
            return yaml.safe_load(path.read_text(encoding="utf-8"))

        return await asyncio.to_thread(_sync)

    async def read_register(self, system_id: str) -> RiskRegister:
        """Read and reconstruct a :class:`RiskRegister` from YAML.

        Raises
        ------
        RegisterNotFoundError
            If ``register.yaml`` does not exist for *system_id* (a ``FileNotFoundError``).
        """
        return RiskRegister.model_validate(await self.read_register_document(system_id))

    # ------------------------------------------------------------------ #
    # Audit log                                                            #
    # ------------------------------------------------------------------ #

    async def append_audit(self, entry: AuditEntry) -> None:
        """Append *entry* to ``audit.jsonl`` and commit the writes staged before it.

        Order: journal (with the log length before the append), one fsynced write of
        the line, rename of each staged file, head file, journal removed. A crash at
        any point leaves a state ``_recover`` can finish (the whole line reached the
        log) or discard (it did not, and any torn part of it is cut off).

        Raises
        ------
        RuntimeError
            If called outside ``unit_of_work()``.
        """
        scope = self._scope()
        if scope is None:
            raise RuntimeError("append_audit must run inside FileStore.unit_of_work().")

        def _sync() -> None:
            created = not self._audit_path.exists()
            journal = {
                "after_seq": entry.seq - 1,
                "log_size": 0 if created else self._audit_path.stat().st_size,
                "files": list(scope.staged),
            }
            _atomic_write(self._journal_path, json.dumps(journal).encode("utf-8"))
            line = json.dumps(entry.model_dump(mode="json"), separators=(",", ":")) + "\n"
            data = line.encode("utf-8")
            fd = os.open(self._audit_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                written = os.write(fd, data)
                if written != len(data):
                    raise OSError(
                        errno.EIO, f"Wrote {written} of {len(data)} bytes to the audit log."
                    )
                os.fsync(fd)
            finally:
                os.close(fd)
            os.chmod(self._audit_path, stat.S_IRUSR | stat.S_IWUSR)
            if created:
                _fsync_dir(self._root)
            staged = [self._root / rel for rel in scope.staged]
            for path in staged:
                os.replace(_pending(path), path)
            for directory in {path.parent for path in staged}:
                _fsync_dir(directory)
            scope.staged.clear()
            self._write_head(entry.seq, entry.entry_hash)
            self._journal_path.unlink()

        await asyncio.to_thread(_sync)

    async def read_audit(
        self,
        system_id: str | None = None,
        since_seq: int = 0,
    ) -> AsyncIterator[AuditEntry]:
        """Async generator streaming :class:`AuditEntry` records.

        Parameters
        ----------
        system_id:
            Filter by system ID string.  Pass ``None`` to yield all entries.
        since_seq:
            Yield only entries with ``seq >= since_seq``.

        Yields
        ------
        AuditEntry

        Raises
        ------
        AuditLogCorruptError
            If a line is not a valid audit entry. A corrupt line is never skipped.
        """

        def _read_lines() -> list[str]:
            if not self._audit_path.exists():
                return []
            return self._audit_path.read_text(encoding="utf-8").splitlines()

        lines = await asyncio.to_thread(_read_lines)

        for lineno, raw in enumerate(lines, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                entry = AuditEntry.model_validate(json.loads(line))
            except ValueError as exc:  # JSONDecodeError and pydantic ValidationError
                raise AuditLogCorruptError(
                    f"Audit log line {lineno} is not a valid entry: {_first_line(exc)}."
                ) from exc
            if entry.seq < since_seq:
                continue
            if system_id is not None and entry.system_id != system_id:
                continue
            yield entry

    async def read_last_audit_entry(self) -> AuditEntry | None:
        """Return the last audit entry, parsing only the final line (O(1) entries)."""

        def _sync() -> AuditEntry | None:
            if not self._audit_path.exists():
                return None
            last_line = ""
            with self._audit_path.open("r", encoding="utf-8") as fh:
                for raw in fh:
                    stripped = raw.strip()
                    if stripped:
                        last_line = stripped
            if not last_line:
                return None
            try:
                return AuditEntry.model_validate(json.loads(last_line))
            except ValueError as exc:  # JSONDecodeError and pydantic ValidationError
                raise AuditLogCorruptError(
                    f"The last audit log line is not a valid entry: {_first_line(exc)}."
                ) from exc

        return await asyncio.to_thread(_sync)

    async def verify_chain(self) -> tuple[bool, list[str]]:
        """Replay the audit chain and validate SHA-256 hash linkage.

        For each entry the method recomputes the expected ``entry_hash``
        and checks that it matches the stored value, and that each entry's
        ``prev_hash`` equals the previous entry's ``entry_hash``.

        Returns
        -------
        tuple[bool, list[str]]
            ``(True, [])`` if the chain is intact, or
            ``(False, [<error>, ...])`` if any integrity failures are found.
        """

        def _sync() -> tuple[bool, list[str]]:
            if not self._audit_path.exists():
                return True, []

            errors: list[str] = []
            prev_hash = "0000000000"  # genesis value, must match AuditEngine._last_entry_hash
            expected_seq = 0

            for lineno, line in enumerate(
                self._audit_path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append(f"Line {lineno}: JSON parse error: {exc}")
                    continue
                try:
                    entry = AuditEntry.model_validate(raw)
                except Exception as exc:
                    errors.append(f"Line {lineno}: validation error: {exc}")
                    continue

                if entry.seq != expected_seq:
                    errors.append(
                        f"Line {lineno}: sequence gap: expected {expected_seq}, got {entry.seq}."
                    )
                if entry.prev_hash != prev_hash:
                    errors.append(
                        f"Line {lineno} (seq={entry.seq}): prev_hash mismatch: "
                        f"expected {prev_hash!r}, stored {entry.prev_hash!r}."
                    )
                computed = FileStore._compute_hash(entry.prev_hash, entry)
                if computed != entry.entry_hash:
                    errors.append(
                        f"Line {lineno} (seq={entry.seq}): entry_hash mismatch: "
                        f"computed {computed!r}, stored {entry.entry_hash!r}."
                    )

                prev_hash = entry.entry_hash
                expected_seq = entry.seq + 1

            ok = len(errors) == 0
            if ok:
                logger.info("Audit chain verified: %d entries, no errors.", expected_seq)
            else:
                logger.warning("Audit chain verification failed: %d error(s).", len(errors))
            return ok, errors

        return await asyncio.to_thread(_sync)
