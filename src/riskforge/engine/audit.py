"""AuditEngine — append-only, hash-chained audit log management."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from riskforge.models.audit import AuditActor, AuditEntry
from riskforge.storage.base import StorageBackend


class AuditChainCorruptError(RuntimeError):
    """Raised when the audit chain fails pre-write validation."""


class AuditEngine:
    """Manages the append-only, hash-chained audit log.

    Every state mutation must go through record(). Each append chains from the
    current tail and verifies that tail entry before writing; full-chain
    verification is available via `riskforge verify`. Exit code 2 is the contract
    for riskforge verify failures (CI-detectable).
    """

    def __init__(self, storage: StorageBackend, actor: AuditActor) -> None:
        self._storage = storage
        self._actor = actor

    async def record(self, event: str, system_id: str, payload: dict) -> AuditEntry:
        """Append a hash-chained entry.

        Chains from the current tail (read inside the unit of work) and verifies that
        tail entry's own hash before appending, so building N entries is O(N), not
        O(N^2). Full-chain verification is the job of ``riskforge verify``.
        """
        async with self._storage.unit_of_work():
            last = await self._storage.read_last_audit_entry()
            if last is None:
                prev_hash = "0000000000"
                seq = 0
            else:
                if self._compute_hash(last.prev_hash, last) != last.entry_hash:
                    raise AuditChainCorruptError(
                        "Audit chain tail is corrupt (last entry hash mismatch). "
                        "Run `riskforge verify` to diagnose."
                    )
                prev_hash = last.entry_hash
                seq = last.seq + 1
            entry = AuditEntry(
                seq=seq,
                event=event,
                timestamp=datetime.now(UTC),
                actor=self._actor,
                system_id=system_id,
                payload=payload,
                prev_hash=prev_hash,
                entry_hash="",  # computed below
            )
            entry.entry_hash = self._compute_hash(prev_hash, entry)
            await self._storage.append_audit(entry)
            return entry

    @staticmethod
    def _compute_hash(prev_hash: str, entry: AuditEntry) -> str:
        data = entry.model_dump(mode="json")
        data["entry_hash"] = ""
        canonical = json.dumps(
            {"prev_hash": prev_hash, **data}, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode()).hexdigest()
