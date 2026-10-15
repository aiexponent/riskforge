"""StorageBackend abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from riskforge.models.audit import AuditEntry
from riskforge.models.register import RiskRegister
from riskforge.models.system import AISystem

# Set to True in ``unit_of_work_state()`` when opening the unit of work finished or
# discarded a change that an earlier one left unfinished.
RECOVERED_STATE_KEY = "riskforge.storage.recovered"
# The ``("register" | "system", system_id)`` pairs written in ``unit_of_work_state()``
# and not yet committed by an audit entry.
WRITTEN_STATE_KEY = "riskforge.storage.written"


@dataclass(frozen=True)
class PendingChange:
    """A change a writer started and has not finished (or never will, after a crash).

    ``systems`` are the systems whose files the change writes.
    """

    systems: frozenset[str]


class StorageBackend(ABC):
    """
    Abstract base class for all RiskForge storage backends.

    Every backend must provide async implementations of the methods below.
    The canonical implementation is :class:`riskforge.storage.filesystem.FileStore`,
    which persists data as YAML/JSONL files inside a ``.riskforge/`` directory.

    New backends (e.g. a cloud object store or a relational database) should
    subclass this ABC and implement every abstract method.

    Design notes
    ------------
    - All methods are ``async`` to allow non-blocking I/O in async runtimes.
    - The filesystem implementation delegates blocking calls to a thread pool
      via ``asyncio.to_thread()``.
    - Exceptions propagate naturally; callers should handle ``FileNotFoundError``
      for missing resources and ``ValueError`` for integrity failures.
    """

    @abstractmethod
    async def init_project(self, project_id: str, metadata: dict) -> None:
        """
        Initialise a new RiskForge project.

        Creates the project root directory, writes a ``riskforge.yaml`` manifest
        with the supplied metadata, and sets restrictive permissions (chmod 700
        for directories, chmod 600 for the manifest file).

        Parameters
        ----------
        project_id:
            A short human-readable identifier for the project,
            e.g. ``"acme-loan-v1"``.
        metadata:
            Arbitrary key-value pairs to store in the manifest, e.g.
            ``{"created_by": "alice@example.com", "organisation": "Acme Corp"}``.

        Raises
        ------
        FileExistsError
            If the project has already been initialised.
        """
        ...

    @abstractmethod
    async def write_system(self, system_id: str, data: AISystem) -> None:
        """
        Persist an :class:`~riskforge.models.system.AISystem` to storage.

        Creates the system sub-directory if it does not already exist and
        writes the system model as ``systems/{system_id}/system.yaml``.

        Parameters
        ----------
        system_id:
            Stable string key for the system, typically ``str(system.id)``.
        data:
            The fully populated AISystem model to persist.
        """
        ...

    @abstractmethod
    async def read_system(self, system_id: str) -> AISystem:
        """
        Read and deserialise an :class:`~riskforge.models.system.AISystem`.

        Parameters
        ----------
        system_id:
            The key used when the system was written.

        Returns
        -------
        AISystem
            The deserialised model.

        Raises
        ------
        FileNotFoundError
            If no system with the given ID exists in storage.
        """
        ...

    @abstractmethod
    async def write_register(self, system_id: str, register: RiskRegister) -> None:
        """
        Persist a :class:`~riskforge.models.register.RiskRegister`.

        Implementations may split the register across multiple files for
        readability (e.g. ``register.yaml`` for metadata and
        ``mitigations.yaml`` for the full mitigation catalogue).

        Parameters
        ----------
        system_id:
            ID of the AI system this register belongs to.
        register:
            The fully populated RiskRegister to persist.
        """
        ...

    @abstractmethod
    async def read_register(self, system_id: str) -> RiskRegister:
        """
        Read and deserialise a :class:`~riskforge.models.register.RiskRegister`.

        Parameters
        ----------
        system_id:
            ID of the AI system whose register should be read.

        Returns
        -------
        RiskRegister
            The deserialised register, including all risk items and mitigations.

        Raises
        ------
        FileNotFoundError
            If no register exists for the given system ID.
        """
        ...

    @abstractmethod
    async def read_register_document(self, system_id: str) -> dict:
        """
        Return the stored register as stored, as a JSON-compatible dict.

        A register written with ``write_register`` must read back equal to
        ``register.model_dump(mode="json")``.

        The document is ``yaml.safe_load`` (or the backend's equivalent) of the bytes
        as stored, never a model serialised again: audit entries record its
        fingerprint (ADR-03 section 3).

        Raises
        ------
        RegisterNotFoundError
            If the system has no register.
        StoredFileCorruptError
            If the stored register does not parse.
        """
        ...

    @abstractmethod
    async def read_system_document(self, system_id: str) -> dict:
        """
        Return the stored system record as stored, as a JSON-compatible dict.

        Raises
        ------
        SystemNotFoundError
            If no system with the given ID exists in storage.
        StoredFileCorruptError
            If the stored record does not parse.
        """
        ...

    @abstractmethod
    async def list_systems(self) -> list[str]:
        """
        Return the IDs of all AI systems currently stored in the project.

        Returns
        -------
        list[str]
            Sorted list of system ID strings.
        """
        ...

    @abstractmethod
    def unit_of_work(self) -> AbstractAsyncContextManager[None]:
        """
        Exclusive, all-or-nothing scope for state changes and their audit entries.

        Entering it again inside an open unit of work joins the open one. While it
        is open, reads return this scope's own writes. A register or system write
        and the audit entry that records it become visible to other readers
        together; if the scope ends without recording an entry, the write is
        discarded, and a scope that ends without an error should raise
        ``RuntimeError`` so the lost write is not silent. A backend may commit at
        each appended entry (the file backend does) or at the end of the
        outermost scope (a database transaction does).

        Returns
        -------
        AsyncContextManager[None]
        """
        ...

    def unit_of_work_state(self) -> dict[str, Any] | None:
        """
        State shared by every scope of the open outermost unit of work.

        Engines keep what one change needs across nested scopes here, such as what the
        integrity check ``AuditEngine`` runs before a change saw. The mapping starts
        empty when the outermost scope opens and is dropped when it ends. A backend
        may add ``RECOVERED_STATE_KEY`` when opening the scope finished or discarded
        an unfinished change, and ``WRITTEN_STATE_KEY`` for the writes staged and not
        yet committed, so engines can tell this change's writes from outside edits. Returns None outside a unit of
        work. This default always returns None, and callers then keep the state
        themselves.

        Returns
        -------
        dict[str, Any] | None
        """
        return None

    @abstractmethod
    async def append_audit(self, entries: AuditEntry | Sequence[AuditEntry]) -> None:
        """
        Append one :class:`~riskforge.models.audit.AuditEntry`, or several chained ones.

        Several entries commit together with the writes staged in the unit of work: all
        of them or none (ADR-03 section 4).

        Implementations must guarantee append-only semantics; existing entries
        must never be modified.  The entry is serialised as a single JSON line
        and appended to ``audit.jsonl``.  Must be called inside
        ``unit_of_work()``; the writes staged in that scope commit with it.

        Parameters
        ----------
        entry:
            The fully populated and hashed AuditEntry to persist.
        """
        ...

    @abstractmethod
    async def read_audit(
        self,
        system_id: str | None = None,
        since_seq: int = 0,
    ) -> AsyncIterator[AuditEntry]:
        """
        Asynchronously stream :class:`~riskforge.models.audit.AuditEntry` records.

        Parameters
        ----------
        system_id:
            If provided, yield only entries whose ``system_id`` matches.
            Pass ``None`` to receive all entries.
        since_seq:
            Only yield entries with ``seq >= since_seq``. Defaults to 0
            (yield all entries).

        Yields
        ------
        AuditEntry
            Entries in ascending sequence order.
        """
        ...

    async def read_last_audit_entry(self) -> AuditEntry | None:
        """Return the most recent audit entry, or ``None`` if the log is empty.

        The audit append path calls this once per write to chain from the tail,
        so backends should override it with an efficient tail read. The default
        streams the whole log, which is correct but O(n) per call.
        """
        last: AuditEntry | None = None
        async for entry in self.read_audit():
            last = entry
        return last

    @abstractmethod
    async def read_audit_head(self) -> dict | None:
        """
        Return ``{"seq": int, "entry_hash": str}`` of the last entry this backend wrote.

        The head is written with each appended entry (ADR-03 section 4). Returns
        ``None`` when no head has been written, as in a project last changed by 1.1.x.

        Raises
        ------
        StoredFileCorruptError
            If the stored head does not parse or lacks ``seq`` or ``entry_hash``.
        """
        ...

    async def read_commit_markers(self) -> tuple[bytes | None, bytes | None]:
        """
        Return ``(journal, head)`` as raw bytes, each ``None`` when absent.

        A reader that does not take the write lock compares the markers before and
        after it reads: a journal, or markers that moved, mean a writer was busy. The
        default suits a backend whose reads see only committed changes.
        """
        return None, None

    async def list_system_directories(self) -> list[str]:
        """
        Return the ids of every system the backend holds anything for, sorted.

        Unlike ``list_systems`` this includes a system whose record is missing. The
        default suits a backend that cannot hold files without a system record.
        """
        return await self.list_systems()

    async def read_pending_change(self) -> PendingChange | None:
        """
        Return the change a writer started and has not finished, or ``None``.

        Raises
        ------
        StoredFileCorruptError
            If the backend's record of the unfinished change is not one it wrote.
        """
        return None

    def protected_paths(self) -> tuple[Path, ...]:
        """The paths of the project's own files and directories, which no export may write.

        An export refuses an output path that is one of these or lies inside one. A
        backend that keeps nothing on the local file system returns none.
        """
        return ()

    def read_project_id(self) -> str | None:
        """The ``project_id`` of the project manifest, or None when it cannot be read."""
        return None

    async def view_after_recovery(self) -> StorageBackend:
        """
        A read-only view of the project as finishing or discarding ``read_pending_change``
        would leave it, without writing anything.

        Raises
        ------
        StoredFileCorruptError
            If the record of the unfinished change does not fit the stored log.
        """
        return self

    @abstractmethod
    async def verify_chain(self) -> tuple[bool, list[str]]:
        """
        Replay the entire audit chain and validate hash linkage.

        Each entry's ``entry_hash`` is recomputed and compared against the
        stored value.  The ``prev_hash`` of each entry is checked against the
        ``entry_hash`` of the preceding entry.

        Returns
        -------
        tuple[bool, list[str]]
            ``(True, [])`` if the chain is intact, or
            ``(False, [<error>, ...])`` listing all integrity failures found.
        """
        ...
