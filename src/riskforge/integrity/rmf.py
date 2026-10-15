"""RMF document rules: schema lookup, content digest, signing messages and strict reading (ADR-04)."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any

from riskforge.integrity.canonical import canonical_json, sha256_hex
from riskforge.integrity.strict_json import loads_strict

if TYPE_CHECKING:
    from riskforge.models.rmf import SignOff

SCHEMA_FILES = {"1.0.0": "rmf-1.0.0.schema.json", "1.1.0": "rmf-1.1.0.schema.json"}

RMF_SIGNING_DOMAIN = b"riskforge.rmf.v1\n"
SIGNOFF_SIGNING_DOMAIN = b"riskforge.signoff.v1\n"

# Under 1.0.0 these are blanked, not removed, exactly as 1.1.3 hashed them.
_BLANKED_1_0_0 = ("sha256_hash", "audit_entry_hash", "signed_by")

# The provenance blocks either verify themselves or describe the act of exporting, and
# change with every export of one register state, so the 1.1.0 digest leaves them out.
_NOT_DIGESTED_1_1_0 = (
    "id",
    "generated_at",
    "sha256_hash",
    "signatures",
    "public_keys",
    "chain_proof",
    "receipt",
)


class UnsupportedRmfVersionError(ValueError):
    """The document declares an ``rmf_schema_version`` this RiskForge does not read."""

    def __init__(self, version: object) -> None:
        super().__init__(
            f"RMF schema version {version!r} is not one this RiskForge reads "
            f"(it reads {', '.join(sorted(SCHEMA_FILES))})."
        )
        self.version = version


class RmfFileError(ValueError):
    """The file cannot be read, is not UTF-8 JSON, or its top level is not an object."""


def load_schema(version: str) -> dict[str, Any]:
    """The bundled JSON Schema for RMF schema ``version``.

    Raises
    ------
    UnsupportedRmfVersionError
        If RiskForge has no schema for ``version``.
    """
    if version not in SCHEMA_FILES:
        raise UnsupportedRmfVersionError(version)
    text = files("riskforge._data.schemas").joinpath(SCHEMA_FILES[version]).read_text("utf-8")
    schema: dict[str, Any] = json.loads(text)
    return schema


def content_digest(document: dict[str, Any]) -> str:
    """The SHA-256 a document's ``sha256_hash`` must equal, by its declared version.

    1.0.0: the whole document with ``sha256_hash``, ``audit_entry_hash`` and
    ``signed_by`` blanked, as 1.1.3 computed it. 1.1.0: the document without ``id``,
    ``generated_at``, ``sha256_hash`` and the provenance blocks, with ``signoffs`` read
    as ``[]`` when absent (ADR-04 section 2).

    Raises
    ------
    UnsupportedRmfVersionError
        If the document declares any other ``rmf_schema_version``.
    """
    version = document.get("rmf_schema_version")
    if version == "1.0.0":
        source = {**document, **dict.fromkeys(_BLANKED_1_0_0, "")}
    elif version == "1.1.0":
        source = {k: v for k, v in document.items() if k not in _NOT_DIGESTED_1_1_0}
        source.setdefault("signoffs", [])
    else:
        raise UnsupportedRmfVersionError(version)
    return sha256_hex(canonical_json(source))


def rmf_signing_message(digest: str) -> bytes:
    """What an RMF signature signs: the domain prefix and the hex content digest."""
    return RMF_SIGNING_DOMAIN + digest.encode("ascii")


def signoff_signing_message(signoff: SignOff) -> bytes:
    """What a sign-off's signature signs: every field but ``signature``, in JSON mode.

    Every field is present, so a sign-off made without a comment and one with ``""``
    give the same message, and ``key_id`` is signed.
    """
    body = signoff.model_dump(mode="json", exclude={"signature"})
    return SIGNOFF_SIGNING_DOMAIN + canonical_json(body)


def read_rmf_file(path: Path) -> dict[str, Any]:
    """Read an RMF file as ADR-04 section 2 requires.

    Raises
    ------
    RmfFileError
        If the file cannot be read, is not UTF-8 JSON, or its top level is not an object.
    StrictJsonError
        If it holds a duplicate key or a non-finite number, which RiskForge never writes.
    """
    try:
        text = path.read_bytes().decode("utf-8")
    except OSError as exc:
        raise RmfFileError(f"it cannot be read: {exc.strerror or exc}.") from exc
    except UnicodeDecodeError as exc:
        raise RmfFileError("it is binary, not JSON; verify the .json export.") from exc
    try:
        data = loads_strict(text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise RmfFileError(f"it is not JSON ({exc}).") from exc
    if not isinstance(data, dict):
        raise RmfFileError("its top level is not a JSON object.")
    return data
