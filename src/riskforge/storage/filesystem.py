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
written before the append lets the next unit of work finish a change whose
entry reached the log, or discard one whose entry did not.

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
    ProjectNotFoundError,
    RegisterNotFoundError,
    SystemNotFoundError,
)

logger = logging.getLogger(__name__)

SENTINEL = ".nodelete"
PENDING_SUFFIX = ".pending"

# ids of the FileStore instances whose unit of work is open in the current context
_ACTIVE_UOW: contextvars.ContextVar[frozenset[int]] = contextvars.ContextVar(
    "riskforge_filestore_uow", default=frozenset()
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
    """

    def __init__(self, project_dir: Path) -> None:
        self._root = project_dir / ".riskforge"
        self._audit_path = self._root / "audit.jsonl"
        self._head_path = self._root / "audit.head.json"
        self._journal_path = self._root / "txn.json"
        self._lock_path = self._root / "audit.lock"
        self._systems_dir = self._root / "systems"
        self._async_lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None
        self._staged: list[Path] = []

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

    def _in_uow(self) -> bool:
        return id(self) in _ACTIVE_UOW.get()

    def _readable(self, path: Path) -> Path:
        """The file a read should see: this unit of work's staged copy, else the committed one."""
        if self._in_uow() and path in self._staged:
            return _pending(path)
        return path

    def _write(self, path: Path, data: bytes) -> None:
        if self._in_uow():
            _atomic_write(_pending(path), data)
            if path not in self._staged:
                self._staged.append(path)
        else:
            _atomic_write(path, data)

    def _tail_seq(self) -> int:
        if not self._audit_path.exists():
            return -1
        last = _last_line(self._audit_path)
        if not last:
            return -1
        try:
            return int(json.loads(last)["seq"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise AuditLogCorruptError(
                f"The last audit log line is not a valid entry: {exc}"
            ) from exc

    def _write_head(self, seq: int, entry_hash: str) -> None:
        head = {"seq": seq, "entry_hash": entry_hash}
        _atomic_write(self._head_path, json.dumps(head).encode("utf-8"))

    def _recover(self) -> None:
        """Finish or discard a change that an earlier unit of work left behind.

        The journal names the staged files and the chain head before the append.
        If the log grew past that head, the append happened, so the staged files
        are renamed into place; otherwise they are deleted. Any other pending or
        temp file is an uncommitted write and is deleted.
        """
        if self._journal_path.exists():
            journal = json.loads(self._journal_path.read_text(encoding="utf-8"))
            committed = self._tail_seq() > journal["after_seq"]
            for rel in journal["files"]:
                final = self._root / rel
                pending = _pending(final)
                if committed and pending.exists():
                    os.replace(pending, final)
                    _fsync_dir(final.parent)
                elif not committed:
                    pending.unlink(missing_ok=True)
            if committed:
                last = json.loads(_last_line(self._audit_path))
                self._write_head(last["seq"], last["entry_hash"])
            self._journal_path.unlink()
            _fsync_dir(self._root)
        if self._systems_dir.exists():
            for leftover in self._systems_dir.glob(f"*/*{PENDING_SUFFIX}"):
                leftover.unlink()
            for leftover in self._systems_dir.glob("*/.*.tmp"):
                leftover.unlink()
        if self._root.exists():
            for leftover in self._root.glob(".*.tmp"):
                leftover.unlink()
        self._staged.clear()

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

        Re-entrant: a nested call joins the open scope. On entry and exit the
        scope finishes or discards anything an interrupted commit left behind.
        """
        active = _ACTIVE_UOW.get()
        if id(self) in active:
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
            while True:
                try:
                    lock.acquire(timeout=0)
                    break
                except Timeout:
                    await asyncio.sleep(0.02)
            token = _ACTIVE_UOW.set(active | {id(self)})
            try:
                await asyncio.to_thread(self._recover)
                try:
                    yield
                finally:
                    await asyncio.to_thread(self._recover)
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

        Order: journal, fsynced append, rename of each staged file, head file,
        journal removed. A crash at any point leaves a state ``_recover`` can
        finish (the entry reached the log) or discard (it did not).

        Raises
        ------
        RuntimeError
            If called outside ``unit_of_work()``.
        """
        if not self._in_uow():
            raise RuntimeError("append_audit must run inside FileStore.unit_of_work().")

        def _sync() -> None:
            journal = {
                "after_seq": entry.seq - 1,
                "files": [str(path.relative_to(self._root)) for path in self._staged],
            }
            _atomic_write(self._journal_path, json.dumps(journal).encode("utf-8"))
            line = json.dumps(entry.model_dump(mode="json"), separators=(",", ":")) + "\n"
            with self._audit_path.open("a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(self._audit_path, stat.S_IRUSR | stat.S_IWUSR)
            for path in self._staged:
                os.replace(_pending(path), path)
            for directory in {path.parent for path in self._staged}:
                _fsync_dir(directory)
            self._staged.clear()
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
                    f"Audit log line {lineno} is not a valid entry: {exc}"
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
            return AuditEntry.model_validate(json.loads(last_line))

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
