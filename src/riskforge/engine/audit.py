"""AuditEngine: append-only, hash-chained audit log management."""

from __future__ import annotations

from datetime import UTC, datetime

from riskforge.integrity.canonical import UnfingerprintableDocumentError, document_fingerprint
from riskforge.integrity.chain import GENESIS_PREV_HASH, compute_entry_hash
from riskforge.models.audit import AuditActor, AuditEntry
from riskforge.storage.base import StorageBackend
from riskforge.storage.errors import RegisterNotFoundError, StoredFileCorruptError

BASELINE_EVENT = "register.baselined"


class AuditChainCorruptError(RuntimeError):
    """Raised when the audit chain fails pre-write validation."""


class AuditEngine:
    """Manages the append-only, hash-chained audit log.

    Every state mutation must go through record(). Each entry carries the fingerprint
    of its system's register as stored after the change (ADR-03), so `riskforge verify`
    can tell when a register was changed outside RiskForge. Exit code 2 is the contract
    for riskforge verify failures (CI-detectable).
    """

    def __init__(self, storage: StorageBackend, actor: AuditActor) -> None:
        self._storage = storage
        self._actor = actor

    async def record(self, event: str, system_id: str, payload: dict) -> AuditEntry:
        """Append a hash-chained entry and return it.

        Chains from the current tail (read inside the unit of work) and verifies that
        tail entry's own hash before appending, so building N entries is O(N), not
        O(N^2). Full-chain verification is the job of ``riskforge verify``.

        The first entry written in a project that has no head file yet (a new project,
        or one last changed by RiskForge 1.1) is followed, in the same unit of work, by
        one ``register.baselined`` entry for every other system on disk, so each system
        is covered by the log from then on (ADR-03 section 6).
        """
        async with self._storage.unit_of_work():
            baseline: list[tuple[str, str, str | None]] = []
            if await self._storage.read_audit_head() is None:
                baseline = await self._baseline_targets(exclude=system_id)
            entry = await self._append(event, system_id, payload)
            for other_id, name, fingerprint in baseline:
                await self._append(BASELINE_EVENT, other_id, {"name": name}, fingerprint)
            return entry

    async def _append(
        self,
        event: str,
        system_id: str,
        payload: dict,
        baseline_fingerprint: str | None = None,
    ) -> AuditEntry:
        last = await self._storage.read_last_audit_entry()
        if last is None:
            prev_hash = GENESIS_PREV_HASH
            seq = 0
        else:
            if compute_entry_hash(last) != last.entry_hash:
                raise AuditChainCorruptError(
                    "Audit chain tail is corrupt (last entry hash mismatch). "
                    "Run `riskforge verify` to diagnose."
                )
            prev_hash = last.entry_hash
            seq = last.seq + 1
        if event == BASELINE_EVENT:
            fingerprint = baseline_fingerprint
        else:
            fingerprint = await self._register_fingerprint(system_id)
        entry = AuditEntry(
            seq=seq,
            event=event,
            timestamp=datetime.now(UTC),
            actor=self._actor,
            system_id=system_id,
            payload=payload,
            prev_hash=prev_hash,
            register_fingerprint=fingerprint,
        )
        entry.entry_hash = compute_entry_hash(entry)
        await self._storage.append_audit(entry)
        return entry

    async def _baseline_targets(self, exclude: str) -> list[tuple[str, str, str | None]]:
        """Each other system's id, name and register fingerprint.

        Read before anything is appended, so a file that cannot be read stops the
        change before any of it is recorded.
        """
        targets: list[tuple[str, str, str | None]] = []
        for other_id in await self._storage.list_systems():
            if other_id == exclude:
                continue
            system = await self._storage.read_system(other_id)
            targets.append((other_id, system.name, await self._register_fingerprint(other_id)))
        return targets

    async def _register_fingerprint(self, system_id: str) -> str | None:
        """The fingerprint of the system's register as stored, or None when it has none.

        Inside a unit of work the store returns the staged register, so the fingerprint
        is taken from the exact YAML text this change wrote.
        """
        if not system_id:
            return None
        try:
            document = await self._storage.read_register_document(system_id)
        except RegisterNotFoundError:
            return None
        try:
            return document_fingerprint(document)
        except UnfingerprintableDocumentError as exc:
            raise StoredFileCorruptError(
                f"register.yaml of system {system_id} {exc}. Run `riskforge verify` for details."
            ) from exc
