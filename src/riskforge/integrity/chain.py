"""Audit hash-chain rules: storage form, entry hash and link checks (ADR-03 section 2)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from riskforge.integrity.canonical import canonical_json, sha256_hex
from riskforge.integrity.signing import decode_public_key, key_id_for, verify_signature
from riskforge.models.audit import AuditEntry

GENESIS_PREV_HASH = "0000000000"

# Added in 2.0.0. Left out of the stored line and the hash when None, so entries
# written by 1.1.x store and hash exactly as before.
OPTIONAL_ENTRY_FIELDS = ("register_fingerprint", "key_id", "signature")

SIGNING_DOMAIN = b"riskforge.audit-entry.v1\n"

BASELINE_EVENT = "register.baselined"

# Events only RiskForge 2.0 and later write (ADR-03 section 7). A log holding one, or
# a fingerprint, was kept with a head file.
EVENTS_SINCE_2_0 = frozenset({"system.created", "register.created", BASELINE_EVENT})


def written_since_2_0(entry: AuditEntry) -> bool:
    return entry.register_fingerprint is not None or entry.event in EVENTS_SINCE_2_0


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


def check_entry_signatures(
    entries: Iterable[AuditEntry], trusted_keys: Sequence[str] | None = None
) -> tuple[list[str], list[str]]:
    """Errors and warnings for the signatures of audit entries (ADR-03 section 2, ADR-04 section 4).

    An entry with ``key_id`` and no ``signature``, or the reverse, is an error. The log
    holds no public keys, so a signature is verified only against ``trusted_keys``
    (base64 raw public keys): an entry signed by a key outside that set, or whose
    signature does not verify, is an error. Without trusted keys, signed entries are
    reported as not checked, in one warning. With trusted keys, unsigned entries are
    counted in one warning, since no trusted key covers them; ``--strict`` makes it a
    finding.
    """
    trusted: dict[str, str] | None = None
    if trusted_keys is not None:
        # The key id only finds the key; the signature is verified with the trusted key itself.
        trusted = {}
        for key in trusted_keys:
            decode_public_key(key)  # ValueError for a key that is not 32 base64 bytes
            trusted[key_id_for(key)] = key
    errors: list[str] = []
    unchecked = 0
    unsigned = 0
    for entry in entries:
        if entry.key_id is None and entry.signature is None:
            unsigned += 1
            continue
        label = f"Audit entry seq {entry.seq}"
        if entry.key_id is None or entry.signature is None:
            if entry.signature is None:
                errors.append(f"{label} has a key_id but no signature.")
            else:
                errors.append(f"{label} has a signature but no key_id.")
            continue
        if trusted is None:
            unchecked += 1
            continue
        key = trusted.get(entry.key_id)
        if key is None:
            errors.append(f"{label} is signed by {entry.key_id}, which is not a trusted key.")
        elif not verify_signature(key, entry_signing_message(entry.entry_hash), entry.signature):
            errors.append(f"{label}: the signature by {entry.key_id} does not verify.")
    warnings: list[str] = []
    if unchecked:
        noun = "entry is" if unchecked == 1 else "entries are"
        warnings.append(
            f"{unchecked} audit {noun} signed, and the signatures were not checked: "
            "no trusted key was given (riskforge verify --trusted-key)."
        )
    if trusted is not None and unsigned:
        noun = "entry is" if unsigned == 1 else "entries are"
        warnings.append(
            f"{unsigned} audit {noun} not signed, so no trusted key covers "
            f"{'it' if unsigned == 1 else 'them'}."
        )
    return errors, warnings
