"""AuditEntry and AuditActor models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class AuditActor(BaseModel):
    type: Literal["human", "ci", "api"]  # classification of the triggering entity
    identity: str  # email, CI job name, API key fingerprint, or "anonymous"


class AuditEntry(BaseModel):
    """
    A single entry in the hash-chained audit log, stored as one line of ``audit.jsonl``.

    Each ``entry_hash`` covers the entry's fields, including ``prev_hash``, the hash of
    the entry before it. Editing, inserting, removing or reordering an entry is
    therefore detectable, unless every later entry is recomputed as well. ADR-03
    describes the hash rule and what ``riskforge verify`` checks beyond the chain.

    ``register_fingerprint``, ``key_id`` and ``signature`` were added in 2.0.0. When one
    is ``None`` it is left out of the stored line and of the hash, so entries written by
    1.1.x keep their hashes.
    """

    seq: int = Field(..., ge=0)  # monotonically increasing, 0-based
    event: str  # e.g. "system.created", "register.created", "rmf.exported"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    actor: AuditActor
    system_id: str  # str(UUID) or "" for project-level events
    payload: dict = Field(default_factory=dict)  # event-specific structured data
    prev_hash: str = ""  # entry_hash of the preceding entry; "0000000000" for seq=0
    entry_hash: str = ""  # SHA-256 of the canonical entry, entry_hash blanked, no signature
    register_fingerprint: str | None = None  # SHA-256 of the stored register after the event
    key_id: str | None = None  # key that signed the entry; covered by entry_hash
    signature: str | None = None  # signs entry_hash, so it is not part of it
