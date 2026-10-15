"""Receipts: build, sign, check against a chain, and read or write receipt files (ADR-04 section 5).

A receipt names the entry the project chain held at a ``seq``. Kept outside the
project, it catches what ADR-03 cannot: a log cut back or rebuilt with
``audit.head.json`` rewritten to match.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from riskforge.integrity.canonical import canonical_json
from riskforge.integrity.signing import decode_public_key, key_id_for, verify_signature
from riskforge.integrity.strict_json import NumberTooLongError, StrictJsonError, loads_strict
from riskforge.models.audit import AuditEntry
from riskforge.models.receipt import Receipt

if TYPE_CHECKING:
    from riskforge.integrity.signing import Ed25519Signer

RECEIPT_SIGNING_DOMAIN = b"riskforge.receipt.v1\n"

SIGNING_FIELDS = ("key_id", "public_key", "signature")

RMF_SCHEMA_WITH_RECEIPT = "1.1.0"

RMF_1_0_0_REFUSAL = (
    "RMF schema 1.0.0 cannot carry a signature, so this file holds no receipt to check."
)


class ReceiptError(ValueError):
    """A receipt could not be used. See the two subclasses for which exit code applies."""


class ReceiptFileError(ReceiptError):
    """The file cannot be read or written, is not JSON, or is not a receipt or RMF file."""


class InvalidReceiptError(ReceiptError):
    """The file was read, and its receipt is refused: a check failure, not a usage error."""


def receipt_signing_message(receipt: Receipt) -> bytes:
    """The prefix plus canonical JSON of the receipt without ``public_key`` and ``signature``.

    Fields that are ``None`` are included as ``null`` (ADR-04 section 4).
    """
    body = receipt.model_dump(mode="json", exclude={"public_key", "signature"})
    return RECEIPT_SIGNING_DOMAIN + canonical_json(body)


def build_receipt(
    head: AuditEntry,
    system_id: str,
    register_fingerprint: str | None,
    signer: Ed25519Signer | None = None,
) -> Receipt:
    """A receipt for ``head``, the last entry of the chain, signed when ``signer`` is given."""
    receipt = Receipt(
        system_id=system_id,
        seq=head.seq,
        entry_hash=head.entry_hash,
        register_fingerprint=register_fingerprint,
        issued_at=datetime.now(UTC),
        key_id=signer.key_id if signer is not None else None,
    )
    if signer is not None:
        receipt.public_key = signer.public_key_b64
        receipt.signature = signer.sign(receipt_signing_message(receipt))
    return receipt


def receipt_to_dict(receipt: Receipt) -> dict[str, Any]:
    """The receipt as written to a file: the signing fields only when it is signed."""
    data = receipt.model_dump(mode="json")
    for name in SIGNING_FIELDS:
        if data[name] is None:
            del data[name]
    return data


def receipt_json(receipt: Receipt) -> str:
    """The receipt as JSON text, as ``riskforge receipt`` prints and writes it."""
    return json.dumps(receipt_to_dict(receipt), indent=2) + "\n"


def _signature_errors(receipt: Receipt, trusted_keys: Sequence[str], label: str) -> list[str]:
    fields = [getattr(receipt, name) for name in SIGNING_FIELDS]
    if all(value is None for value in fields):
        if trusted_keys:
            return [f"{label} is not signed, and a trusted key is required."]
        return []
    if any(value is None for value in fields):
        return [f"{label}: key_id, public_key and signature must all be present when it is signed."]
    try:
        raw = decode_public_key(receipt.public_key)
    except ValueError as exc:
        return [f"{label}: its public_key is not an Ed25519 public key ({exc})."]
    # The key of a receipt read from its own file is its own public_key (ADR-04 section 4
    # step 5); an embedded receipt's public_key was matched to its record when it was read.
    if receipt.key_id != key_id_for(receipt.public_key):
        return [f"{label}: its key_id does not match its public_key."]
    if not verify_signature(
        receipt.public_key, receipt_signing_message(receipt), receipt.signature
    ):
        return [f"{label}: the signature does not verify."]
    if trusted_keys and raw not in {decode_public_key(key) for key in trusted_keys}:
        return [f"{label} is signed by {receipt.key_id}, which is not a trusted key."]
    return []


def check_receipt(
    receipt: Receipt,
    entries: Sequence[AuditEntry],
    trusted_keys: Sequence[str] = (),
    label: str = "Receipt",
    chain_name: str = "the audit log",
) -> list[str]:
    """Every reason ``receipt`` fails against ``entries``; empty when it holds.

    A signed receipt must verify with its own key. With ``trusted_keys`` (base64 raw
    public keys) it must be signed, and the key it verified with must be one of them,
    compared as raw bytes. The chain must hold an entry at the receipt's ``seq`` with
    the receipt's ``entry_hash``, and the last register fingerprint it records for the
    receipt's system up to that ``seq`` must be the receipt's ``register_fingerprint``
    (both ``None`` when it records none). ``chain_name`` names ``entries`` in messages,
    such as "the chain proof" for the entries embedded in an RMF file.
    """
    errors = _signature_errors(receipt, trusted_keys, label)
    at_seq = next((entry for entry in entries if entry.seq == receipt.seq), None)
    if at_seq is None:
        errors.append(
            f"{label}: {chain_name} has no entry at seq {receipt.seq}, so it was truncated "
            "or replaced."
        )
    elif at_seq.entry_hash != receipt.entry_hash:
        errors.append(
            f"{label}: the entry {chain_name} holds at seq {receipt.seq} is not the one the receipt "
            "names, so it was rewritten."
        )
    recorded = _fingerprint_at(entries, receipt.system_id, receipt.seq)
    if recorded != receipt.register_fingerprint:
        errors.append(
            f"{label}: its register fingerprint for system {receipt.system_id} is "
            f"{receipt.register_fingerprint or 'none'}, but {chain_name} records "
            f"{recorded or 'none'} for that system up to seq {receipt.seq}."
        )
    return errors


def _fingerprint_at(entries: Sequence[AuditEntry], system_id: str, seq: int) -> str | None:
    """The last register fingerprint ``entries`` record for ``system_id`` up to ``seq``."""
    recorded: str | None = None
    for entry in entries:
        if (
            entry.seq <= seq
            and entry.system_id == system_id
            and entry.register_fingerprint is not None
        ):
            recorded = entry.register_fingerprint
    return recorded


def _validate(source: dict[str, Any]) -> Receipt:
    try:
        return Receipt.model_validate(source)
    except ValidationError as exc:
        fields = sorted({".".join(str(part) for part in error["loc"]) for error in exc.errors()})
        raise InvalidReceiptError(
            f"it is not a valid receipt ({exc.error_count()} field error(s): {', '.join(fields)})."
        ) from exc


def _resolve_embedded_key(receipt: Receipt, public_keys: Any) -> None:
    """ADR-04 section 4 steps 1 to 4 for the receipt embedded in an RMF file."""
    if not isinstance(public_keys, list):
        raise InvalidReceiptError("its public_keys is not a list.")
    records: dict[str, bytes] = {}
    for record in public_keys:
        if not isinstance(record, dict) or not isinstance(record.get("key_id"), str):
            raise InvalidReceiptError("a public_keys record has no key_id.")
        key_id = record["key_id"]
        if key_id in records:
            raise InvalidReceiptError(f"public_keys holds two records for key id {key_id}.")
        if record.get("algorithm") != "ed25519":
            raise InvalidReceiptError(f"public_keys record {key_id}: its algorithm is not ed25519.")
        try:
            raw = decode_public_key(record.get("public_key"))
        except ValueError as exc:
            raise InvalidReceiptError(
                f"public_keys record {key_id}: its public_key does not decode to 32 bytes ({exc})."
            ) from exc
        if key_id_for(record["public_key"]) != key_id:
            raise InvalidReceiptError(
                f"public_keys record {key_id}: its key_id is not the key id of its public_key."
            )
        records[key_id] = raw
    if receipt.key_id is None:
        return
    if receipt.key_id not in records:
        raise InvalidReceiptError(
            f"the receipt's key_id {receipt.key_id} has no record in public_keys."
        )
    if receipt.public_key is not None:
        try:
            embedded = decode_public_key(receipt.public_key)
        except ValueError as exc:
            raise InvalidReceiptError(f"the receipt's public_key is not valid ({exc}).") from exc
        if embedded != records[receipt.key_id]:
            raise InvalidReceiptError(
                "the receipt's public_key differs from the public_keys record for its key_id."
            )


def receipt_from_document(data: Any) -> Receipt:
    """The receipt in a parsed receipt file, or the ``receipt`` block of an RMF 1.1.0 file.

    Raises
    ------
    ReceiptFileError
        If ``data`` is neither a receipt nor an RMF document, or declares a
        ``receipt_version`` or ``rmf_schema_version`` this RiskForge does not read.
    InvalidReceiptError
        If the receipt does not validate, an RMF file's receipt key does not resolve
        through its ``public_keys`` (ADR-04 section 4), or the RMF file declares schema
        1.0.0, which holds no receipt.
    """
    if not isinstance(data, dict):
        raise ReceiptFileError("the top level is not a JSON object.")
    if "rmf_schema_version" in data:
        version = data["rmf_schema_version"]
        if version == "1.0.0":
            raise InvalidReceiptError(RMF_1_0_0_REFUSAL)
        if version != RMF_SCHEMA_WITH_RECEIPT:
            raise ReceiptFileError(
                f"RMF schema version {version!r} is not one this RiskForge reads."
            )
        source = data.get("receipt")
        if not isinstance(source, dict):
            raise InvalidReceiptError("the RMF file holds no receipt.")
        receipt = _validate(source)
        _resolve_embedded_key(receipt, data.get("public_keys"))
        return receipt
    if "receipt_version" not in data:
        raise ReceiptFileError(
            "it is not a receipt or an RMF file (it has no receipt_version or rmf_schema_version)."
        )
    if data["receipt_version"] != "1":
        raise ReceiptFileError(
            f"receipt_version {data['receipt_version']!r} is not one this RiskForge reads."
        )
    return _validate(data)


def read_receipt_file(path: Path) -> Receipt:
    """Read a receipt file, or an RMF file's receipt, as ADR-04 section 2 requires.

    Raises
    ------
    ReceiptFileError
        If the file cannot be read, is not UTF-8 JSON, or is not a receipt or RMF file.
    InvalidReceiptError
        If it holds a duplicate key, a non-finite number, an integer too long to read or
        nesting deeper than RiskForge writes, or its receipt is refused.
    """
    try:
        text = path.read_bytes().decode("utf-8")
    except OSError as exc:
        raise ReceiptFileError(f"it cannot be read: {exc.strerror or exc}.") from exc
    except UnicodeDecodeError as exc:
        raise ReceiptFileError("it is not JSON (it is not UTF-8 text).") from exc
    try:
        data = loads_strict(text)
    except (StrictJsonError, NumberTooLongError) as exc:
        # RiskForge never writes any of these, so the receipt is refused (exit 2).
        raise InvalidReceiptError(f"it holds {exc}, which RiskForge never writes.") from exc
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ReceiptFileError(f"it is not JSON ({exc}).") from exc
    return receipt_from_document(data)


def write_receipt_file(path: Path, receipt: Receipt) -> None:
    """Write ``receipt`` to a new file at ``path``; never overwrite.

    On POSIX systems the file is created with mode 600. If writing fails or is
    interrupted, the file this call created is removed.

    Raises
    ------
    ReceiptFileError
        If ``path`` exists, its directory is missing, or the file cannot be written.
    """
    data = receipt_json(receipt).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        # O_EXCL: fail instead of following a symlink or replacing a file created meanwhile.
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise ReceiptFileError(
            f"{path} already exists. RiskForge never overwrites a receipt; choose another --output."
        ) from exc
    except OSError as exc:
        raise ReceiptFileError(f"Cannot write {path}: {exc.strerror or exc}.") from exc
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException as exc:
        path.unlink(missing_ok=True)
        if isinstance(exc, OSError):
            raise ReceiptFileError(f"Cannot write {path}: {exc.strerror or exc}.") from exc
        raise
