"""Canonical JSON and SHA-256 helpers for the audit chain and register fingerprints (ADR-03)."""

from __future__ import annotations

import hashlib
import json
from typing import Any


class UnfingerprintableDocumentError(ValueError):
    """A stored document holds a value canonical JSON cannot encode.

    A YAML date, timestamp, ``!!binary`` or ``!!set`` value, or a mapping with keys of
    mixed types, loads into a Python value that ``json.dumps`` rejects.
    """


def canonical_json(value: Any) -> bytes:
    """The bytes RiskForge hashes: sorted keys, no spaces, ASCII escapes, as in 1.1.3."""
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def document_fingerprint(document: Any) -> str:
    """SHA-256 of a stored register document, as the audit chain records it.

    ``document`` is ``yaml.safe_load`` of the stored bytes, not a model serialised again.

    Raises
    ------
    UnfingerprintableDocumentError
        If the document holds a value canonical JSON cannot encode.
    """
    try:
        encoded = canonical_json(document)
    except (TypeError, ValueError) as exc:
        raise UnfingerprintableDocumentError(
            f"holds a value that canonical JSON cannot encode ({exc})"
        ) from exc
    return sha256_hex(encoded)
