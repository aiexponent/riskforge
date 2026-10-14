"""Audit hash-chain rules: storage form, entry hash and link checks (ADR-03 section 2)."""

from __future__ import annotations

from collections.abc import Iterable

from riskforge.integrity.canonical import canonical_json, sha256_hex
from riskforge.models.audit import AuditEntry

GENESIS_PREV_HASH = "0000000000"

# Added in 2.0.0. Left out of the stored line and the hash when None, so entries
# written by 1.1.x store and hash exactly as before.
OPTIONAL_ENTRY_FIELDS = ("register_fingerprint", "key_id", "signature")

SIGNING_DOMAIN = b"riskforge.audit-entry.v1\n"


def entry_to_dict(entry: AuditEntry) -> dict:
    """The entry as it is stored and hashed. ``None`` inside ``payload`` is kept."""
    data = entry.model_dump(mode="json")
    for name in OPTIONAL_ENTRY_FIELDS:
        if data[name] is None:
            del data[name]
    return data


def compute_entry_hash(entry: AuditEntry) -> str:
    """SHA-256 of the canonical entry with ``entry_hash`` blanked and ``signature`` removed.

    ``prev_hash`` is hashed as stored; ``verify_links`` checks it separately.
    """
    data = entry_to_dict(entry)
    data.pop("signature", None)  # the signature signs this hash, so it cannot be part of it
    data["entry_hash"] = ""
    return sha256_hex(canonical_json(data))


def entry_signing_message(entry_hash: str) -> bytes:
    return SIGNING_DOMAIN + entry_hash.encode("ascii")


def verify_links(entries: Iterable[tuple[str, AuditEntry]]) -> list[str]:
    """Check seq order, prev_hash links and entry hashes. Labels name each entry in errors."""
    errors: list[str] = []
    prev_hash = GENESIS_PREV_HASH
    expected_seq = 0
    for label, entry in entries:
        if entry.seq != expected_seq:
            errors.append(f"{label}: sequence gap, expected {expected_seq}, got {entry.seq}.")
        if entry.prev_hash != prev_hash:
            errors.append(
                f"{label} (seq={entry.seq}): prev_hash mismatch, expected {prev_hash!r}, "
                f"stored {entry.prev_hash!r}."
            )
        computed = compute_entry_hash(entry)
        if computed != entry.entry_hash:
            errors.append(
                f"{label} (seq={entry.seq}): entry_hash mismatch, computed {computed!r}, "
                f"stored {entry.entry_hash!r}."
            )
        prev_hash = entry.entry_hash
        expected_seq = entry.seq + 1
    return errors
