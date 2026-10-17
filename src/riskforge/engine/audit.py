"""AuditEngine: append-only, hash-chained audit log management."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from riskforge.engine.integrity import (
    ChangeGuard,
    IntegrityReport,
    change_guard,
    checked_unit_of_work,
    file_digest,
    read_register_checked,
    read_system_checked,
)
from riskforge.integrity.canonical import UnfingerprintableDocumentError, document_fingerprint
from riskforge.integrity.chain import (
    BASELINE_EVENT,
    GENESIS_PREV_HASH,
    compute_entry_hash,
    entry_signing_message,
)
from riskforge.models.audit import AuditActor, AuditEntry
from riskforge.models.register import RiskRegister
from riskforge.models.system import AISystem
from riskforge.storage.base import StorageBackend
from riskforge.storage.errors import RegisterNotFoundError, StoredFileCorruptError

if TYPE_CHECKING:
    from riskforge.integrity.signing import Ed25519Signer

__all__ = ["BASELINE_EVENT", "AuditChainCorruptError", "AuditEngine", "StagedEntries"]


class AuditChainCorruptError(RuntimeError):
    """Raised when the audit chain fails pre-write validation."""


@dataclass(frozen=True)
class StagedEntries:
    """Entries built by ``AuditEngine.stage`` and not appended yet.

    ``system_digests`` holds a digest of each system file the change wrote, so the guard
    can move on to what was committed.
    """

    entries: tuple[AuditEntry, ...]
    system_digests: dict[str, str]


class AuditEngine:
    """Manages the append-only, hash-chained audit log.

    Every state mutation must go through record(). Each entry carries the fingerprint
    of its system's register as stored after the change (ADR-03), so `riskforge verify`
    can tell when a register was changed outside RiskForge. Nothing is appended to a
    project that fails its integrity check. Exit code 2 is the contract for
    riskforge verify failures (CI-detectable).

    With a ``signer``, every entry it writes names the signer's ``key_id``, which the
    entry hash covers, and carries an Ed25519 signature over that hash, which it does not
    (ADR-03 section 2). The free CLI does not sign entries.
    """

    def __init__(
        self, storage: StorageBackend, actor: AuditActor, signer: Ed25519Signer | None = None
    ) -> None:
        self._storage = storage
        self._actor = actor
        self._signer = signer

    def unit_of_work(self) -> AbstractAsyncContextManager[IntegrityReport | None]:
        """The storage unit of work, entered only when the project passes its integrity check.

        Open a change with this rather than ``storage.unit_of_work()``, so the check
        runs before the change stages anything. The check runs once per outermost
        unit of work (see ``checked_unit_of_work``).

        Raises
        ------
        IntegrityError
            If the project fails its integrity check.
        """
        return checked_unit_of_work(self._storage)

    async def read_register(self, system_id: str) -> RiskRegister:
        """The register, compared with what this change's integrity check saw.

        Raises
        ------
        RegisterNotFoundError
            If the system has no register, and the check saw none either.
        IntegrityError
            If the register changed outside RiskForge after the check.
        """
        return await read_register_checked(self._storage, system_id)

    async def read_system(self, system_id: str) -> AISystem:
        """The system record, compared with what this change's integrity check saw.

        Raises
        ------
        SystemNotFoundError
            If there is no such system, and the check saw none either.
        IntegrityError
            If the system file changed outside RiskForge after the check.
        """
        return await read_system_checked(self._storage, system_id)

    def wrote_register(self, system_id: str) -> None:
        """Note that this change wrote the system's register, so ``record`` takes it as is."""
        self._guard().written_registers.add(system_id)

    def wrote_system(self, system_id: str) -> None:
        """Note that this change wrote the system file."""
        self._guard().written_systems.add(system_id)

    def _guard(self) -> ChangeGuard:
        guard = change_guard(self._storage)
        if guard is None:
            raise RuntimeError("Changes must run inside AuditEngine.unit_of_work().")
        return guard

    @property
    def signer(self) -> Ed25519Signer | None:
        """The key that signs the entries this engine writes, or None."""
        return self._signer

    async def record(self, event: str, system_id: str, payload: dict) -> AuditEntry:
        """Append a hash-chained entry and return it.

        Runs in ``unit_of_work()``, so nothing is appended unless the whole project
        passed its integrity check in this outermost unit of work. Every register the
        entries fingerprint must read as that check saw it unless this change wrote it
        (``wrote_register``), so a register changed outside RiskForge after the check is
        refused, not recorded. A unit of work opened on the storage directly, with
        writes already staged, is checked here with those writes in place, so it fails:
        open changes with ``unit_of_work()``.

        Chains from the current tail (read inside the unit of work) and verifies that
        tail entry's own hash before appending.

        The first entry written in a project that has no head file yet (a new project,
        or one last changed by RiskForge 1.1) is followed, in the same unit of work, by
        one ``register.baselined`` entry for every other system the check saw, so each
        system is covered by the log from then on (ADR-03 section 6). The check has
        passed by then, so a register changed outside RiskForge is never baselined.

        Raises
        ------
        IntegrityError
            If the project fails its integrity check, or a file it saw changed since.
            Nothing is appended.
        """
        async with self.unit_of_work():
            return await self.commit(await self.stage(event, system_id, payload))

    async def stage(self, event: str, system_id: str, payload: dict) -> StagedEntries:
        """Build, without appending, the entries ``record`` would append now.

        For a change that must show its entries before it commits them, as an export
        shows them in its chain proof (ADR-04 section 7). Must run inside
        ``unit_of_work()``, which holds the lock, so no other entry can come first;
        ``commit`` appends them exactly as built. If the unit of work ends without
        ``commit``, nothing is appended and the writes staged with them are discarded.

        Raises
        ------
        RuntimeError
            If called outside ``unit_of_work()``.
        IntegrityError
            If a file the check saw changed since.
        AuditChainCorruptError
            If the last entry of the log does not match its own hash.
        """
        guard = self._guard()
        baseline: list[tuple[str, str, str | None]] = []
        if await self._storage.read_audit_head() is None:
            baseline = await self._baseline_targets(guard, exclude=system_id)
        last = await self._storage.read_last_audit_entry()
        if last is None:
            prev_hash, seq = GENESIS_PREV_HASH, 0
        else:
            if compute_entry_hash(last) != last.entry_hash:
                raise AuditChainCorruptError(
                    "Audit chain tail is corrupt (last entry hash mismatch). "
                    "Run `riskforge verify` to diagnose."
                )
            prev_hash, seq = last.entry_hash, last.seq + 1
        entries = [
            self._entry(
                seq,
                prev_hash,
                event,
                system_id,
                payload,
                await self._register_fingerprint(guard, system_id),
            )
        ]
        for other_id, name, fingerprint in baseline:
            previous = entries[-1]
            entries.append(
                self._entry(
                    previous.seq + 1,
                    previous.entry_hash,
                    BASELINE_EVENT,
                    other_id,
                    {"name": name},
                    fingerprint,
                )
            )
        written = {
            sid for kind, sid in guard.written_in_storage() if kind == "system"
        } | guard.written_systems
        systems = {
            sid: file_digest(await self._storage.read_system_document(sid)) for sid in written
        }
        return StagedEntries(entries=tuple(entries), system_digests=systems)

    async def commit(self, staged: StagedEntries) -> AuditEntry:
        """Append ``staged`` exactly as built, with the writes staged before; return its first entry.

        Raises
        ------
        RuntimeError
            If called outside ``unit_of_work()``.
        AuditChainCorruptError
            If the log no longer ends where it ended when the entries were staged.
        """
        guard = self._guard()
        first = staged.entries[0]
        last = await self._storage.read_last_audit_entry()
        tail = (GENESIS_PREV_HASH, 0) if last is None else (last.entry_hash, last.seq + 1)
        if tail != (first.prev_hash, first.seq):
            raise AuditChainCorruptError(
                "The audit log changed after these entries were staged, so they were not "
                "appended. Run `riskforge verify` to diagnose."
            )
        # One append, so the change and its baseline entries commit together.
        await self._storage.append_audit(list(staged.entries))
        for entry in staged.entries:
            guard.registers[entry.system_id] = entry.register_fingerprint
        guard.systems.update(staged.system_digests)
        guard.written_registers.clear()
        guard.written_systems.clear()
        return first

    def _entry(
        self,
        seq: int,
        prev_hash: str,
        event: str,
        system_id: str,
        payload: dict,
        fingerprint: str | None,
    ) -> AuditEntry:
        entry = AuditEntry(
            seq=seq,
            event=event,
            timestamp=datetime.now(UTC),
            actor=self._actor,
            system_id=system_id,
            payload=payload,
            prev_hash=prev_hash,
            register_fingerprint=fingerprint,
            key_id=self._signer.key_id if self._signer is not None else None,
        )
        entry.entry_hash = compute_entry_hash(entry)
        if self._signer is not None:
            entry.signature = self._signer.sign(entry_signing_message(entry.entry_hash))
        return entry

    async def _baseline_targets(
        self, guard: ChangeGuard, exclude: str
    ) -> list[tuple[str, str, str | None]]:
        """Each other system the check saw: its id, name and register fingerprint.

        Read before anything is appended, so a file that cannot be read, or changed
        since the check, stops the change before any of it is recorded.
        """
        targets: list[tuple[str, str, str | None]] = []
        for other_id in sorted(guard.systems):
            if other_id == exclude or guard.systems[other_id] is None:
                continue
            system = await read_system_checked(self._storage, other_id)
            targets.append(
                (other_id, system.name, await self._register_fingerprint(guard, other_id))
            )
        return targets

    async def _register_fingerprint(self, guard: ChangeGuard, system_id: str) -> str | None:
        """The fingerprint of the system's register as stored, or None when it has none.

        Inside a unit of work the store returns the staged register, so the fingerprint
        is taken from the exact YAML text this change wrote. A register this change did
        not write must read as the check saw it.
        """
        if not system_id:
            return None
        try:
            document = await self._storage.read_register_document(system_id)
        except RegisterNotFoundError:
            guard.confirm_register(system_id, None)
            return None
        guard.confirm_register(system_id, file_digest(document))
        try:
            return document_fingerprint(document)
        except UnfingerprintableDocumentError as exc:
            raise StoredFileCorruptError(
                f"register.yaml of system {system_id} {exc}. Run `riskforge verify` for details."
            ) from exc
