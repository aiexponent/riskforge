"""FileStore — OSS storage backend using YAML + JSONL files.

All data is persisted under ``<project_dir>/.riskforge/`` using a combination
of YAML files (human-readable, diffable) and JSONL for the append-only audit
log.

Directory layout
----------------
::

    <project_dir>/
    ├── riskforge.yaml          chmod 600  — project manifest
    └── .riskforge/             chmod 700
        ├── audit.jsonl         chmod 600  — append-only audit chain
        ├── .nodelete                      — sentinel preventing accidental deletion
        └── systems/
            └── <system_id>/
                ├── system.yaml
                ├── register.yaml
                ├── mitigations.yaml
                └── exports/
                    └── <export_id>.<fmt>

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
import hashlib
import json
import logging
import os
import stat
import subprocess
import warnings
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from pathlib import Path

import yaml
from filelock import FileLock, Timeout

from riskforge.models.audit import AuditEntry
from riskforge.models.register import RiskRegister
from riskforge.models.system import AISystem
from riskforge.storage.base import StorageBackend
from riskforge.storage.errors import (
    ProjectExistsError,
    ProjectNotFoundError,
    RegisterNotFoundError,
    SystemNotFoundError,
)

logger = logging.getLogger(__name__)

SENTINEL = ".nodelete"


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
        self._async_lock = None
        self._systems_dir = self._root / "systems"

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
            raise ValueError(
                f"Invalid system id '{system_id}': must not contain path separators or '..'."
            )
        return self._systems_dir / system_id

    def _exports_dir(self, system_id: str) -> Path:
        return self._system_dir(system_id) / "exports"

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
            if manifest_path.exists():
                raise ProjectExistsError(
                    f"A RiskForge project already exists in {self._root.parent.resolve()} "
                    "(riskforge.yaml found)."
                )
            content = {"project_id": project_id, "schema_version": "1.0.0", **metadata}
            manifest_path.write_text(
                yaml.dump(content, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            os.chmod(manifest_path, stat.S_IRUSR | stat.S_IWUSR)
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
            path = sdir / "system.yaml"
            path.write_text(
                yaml.dump(data.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            logger.debug("Wrote system '%s' to %s", system_id, path)

        await asyncio.to_thread(_sync)

    async def read_system(self, system_id: str) -> AISystem:
        """Read ``systems/{system_id}/system.yaml`` and return an :class:`AISystem`.

        Raises
        ------
        SystemNotFoundError
            If the YAML file does not exist (a ``FileNotFoundError``).
        """

        def _sync() -> AISystem:
            path = self._system_dir(system_id) / "system.yaml"
            if not path.exists():
                raise SystemNotFoundError(f"No system '{system_id}' in this project.")
            return AISystem.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

        return await asyncio.to_thread(_sync)

    async def list_systems(self) -> list[str]:
        """Return sorted list of all system IDs under ``systems/``."""

        def _sync() -> list[str]:
            if not self._systems_dir.exists():
                return []
            return sorted(entry.name for entry in self._systems_dir.iterdir() if entry.is_dir())

        return await asyncio.to_thread(_sync)

    # ------------------------------------------------------------------ #
    # Risk register CRUD                                                   #
    # ------------------------------------------------------------------ #

    async def write_register(self, system_id: str, register: RiskRegister) -> None:
        """Persist a :class:`RiskRegister` as two files.

        Writes:
        - ``systems/{system_id}/register.yaml`` — register metadata + risk items
        - ``systems/{system_id}/mitigations.yaml`` — flat mitigation catalogue
          with back-links to each parent risk item
        """

        def _sync() -> None:
            self._ensure_dirs()
            sdir = self._system_dir(system_id)
            sdir.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(sdir, stat.S_IRWXU)

            # Serialise register; mitigations are also included inline for
            # simple reconstruction and separately for readability.
            reg_dict = register.model_dump(mode="json")

            # Build flat mitigation catalogue with risk_item_id back-link
            mitigations_catalogue = []
            for item in reg_dict.get("items", []):
                for m in item.get("mitigations", []):
                    m_copy = dict(m)
                    m_copy["_risk_item_id"] = item["id"]
                    mitigations_catalogue.append(m_copy)

            reg_path = sdir / "register.yaml"
            reg_path.write_text(
                yaml.dump(reg_dict, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            os.chmod(reg_path, stat.S_IRUSR | stat.S_IWUSR)

            mit_path = sdir / "mitigations.yaml"
            mit_path.write_text(
                yaml.dump(
                    {"mitigations": mitigations_catalogue},
                    sort_keys=False,
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            os.chmod(mit_path, stat.S_IRUSR | stat.S_IWUSR)
            logger.debug(
                "Wrote register for system '%s' (%d items, %d mitigations)",
                system_id,
                len(reg_dict.get("items", [])),
                len(mitigations_catalogue),
            )

        await asyncio.to_thread(_sync)

    async def read_register(self, system_id: str) -> RiskRegister:
        """Read and reconstruct a :class:`RiskRegister` from YAML.

        Raises
        ------
        RegisterNotFoundError
            If ``register.yaml`` does not exist for *system_id* (a ``FileNotFoundError``).
        """

        def _sync() -> RiskRegister:
            reg_path = self._system_dir(system_id) / "register.yaml"
            if not reg_path.exists():
                raise RegisterNotFoundError(f"System '{system_id}' has no risk register yet.")
            raw = yaml.safe_load(reg_path.read_text(encoding="utf-8"))
            return RiskRegister.model_validate(raw)

        return await asyncio.to_thread(_sync)

    # ------------------------------------------------------------------ #
    # Audit log                                                            #
    # ------------------------------------------------------------------ #

    @contextlib.asynccontextmanager
    async def audit_lock(self) -> AbstractAsyncContextManager[None]:
        """Acquire an exclusive file lock for mutating the audit chain."""
        lock_path = self._root / "audit.lock"

        if getattr(self, "_async_lock", None) is None:
            self._async_lock = asyncio.Lock()

        async with self._async_lock:
            self._ensure_dirs()
            lock = FileLock(lock_path)

            while True:
                try:
                    lock.acquire(timeout=0)
                    break
                except Timeout:
                    await asyncio.sleep(0.05)

            try:
                yield
            finally:
                lock.release()

    async def append_audit(self, entry: AuditEntry) -> None:
        """Append *entry* as a single JSON line to ``audit.jsonl``.

        The file is opened in append mode.  Callers in concurrent environments
        should serialise access externally; no file-level locking is applied.
        """

        def _sync() -> None:
            self._ensure_dirs()
            line = json.dumps(entry.model_dump(mode="json"), separators=(",", ":")) + "\n"
            with self._audit_path.open("a", encoding="utf-8") as fh:
                fh.write(line)
            os.chmod(self._audit_path, stat.S_IRUSR | stat.S_IWUSR)

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
        """

        def _read_lines() -> list[str]:
            if not self._audit_path.exists():
                return []
            return self._audit_path.read_text(encoding="utf-8").splitlines()

        lines = await asyncio.to_thread(_read_lines)

        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("Skipping malformed audit line: %s", exc)
                continue
            entry = AuditEntry.model_validate(raw)
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
            prev_hash = "0000000000"  # genesis value — must match AuditEngine._last_entry_hash
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
                    errors.append(f"Line {lineno}: JSON parse error — {exc}")
                    continue
                try:
                    entry = AuditEntry.model_validate(raw)
                except Exception as exc:
                    errors.append(f"Line {lineno}: validation error — {exc}")
                    continue

                if entry.seq != expected_seq:
                    errors.append(
                        f"Line {lineno}: sequence gap — expected {expected_seq}, got {entry.seq}."
                    )
                if entry.prev_hash != prev_hash:
                    errors.append(
                        f"Line {lineno} (seq={entry.seq}): prev_hash mismatch — "
                        f"expected {prev_hash!r}, stored {entry.prev_hash!r}."
                    )
                computed = FileStore._compute_hash(entry.prev_hash, entry)
                if computed != entry.entry_hash:
                    errors.append(
                        f"Line {lineno} (seq={entry.seq}): entry_hash mismatch — "
                        f"computed {computed!r}, stored {entry.entry_hash!r}."
                    )

                prev_hash = entry.entry_hash
                expected_seq = entry.seq + 1

            ok = len(errors) == 0
            if ok:
                logger.info("Audit chain verified — %d entries, no errors.", expected_seq)
            else:
                logger.warning("Audit chain verification failed — %d error(s).", len(errors))
            return ok, errors

        return await asyncio.to_thread(_sync)

    # ------------------------------------------------------------------ #
    # Exports                                                              #
    # ------------------------------------------------------------------ #

    async def write_export(
        self,
        system_id: str,
        export_id: str,
        payload: bytes,
        fmt: str,
    ) -> str:
        """Write a binary export artefact to ``systems/{system_id}/exports/``.

        Returns
        -------
        str
            Absolute path to the written file.
        """

        def _sync() -> str:
            exports_dir = self._exports_dir(system_id)
            exports_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(exports_dir, stat.S_IRWXU)
            out = exports_dir / f"{export_id}.{fmt}"
            out.write_bytes(payload)
            os.chmod(out, stat.S_IRUSR | stat.S_IWUSR)
            logger.debug(
                "Wrote export '%s.%s' for system '%s' (%d bytes)",
                export_id,
                fmt,
                system_id,
                len(payload),
            )
            return str(out.resolve())

        return await asyncio.to_thread(_sync)
