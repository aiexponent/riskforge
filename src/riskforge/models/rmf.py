"""RiskManagementFile: the Article 9 / Annex IV export artefact, RMF schema 1.1.0 (ADR-04)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_serializer,
    model_serializer,
)

from riskforge.models.audit import AuditEntry
from riskforge.models.receipt import Receipt
from riskforge.models.register import RiskRegister
from riskforge.models.requirements import TestRequirement

RMF_SCHEMA_VERSION = "1.1.0"

__all__ = [
    "RMF_SCHEMA_VERSION",
    "ChainProof",
    "CrossReference",
    "PublicKeyRecord",
    "RiskManagementFile",
    "RmfSignature",
    "SignOff",
    "TestRequirement",
    "rmf_document",
]


class CrossReference(BaseModel):
    """Maps a cluster of risk items to regulatory and framework references."""

    article_ref: str  # e.g. "Art.9(2)(a)"
    risk_item_ids: list[UUID]
    nist_rmf_ref: str = ""  # e.g. "MAP 1.1"
    iso42001_ref: str = ""  # e.g. "Clause 6.1"


class PublicKeyRecord(BaseModel):
    """A key that signed the file, a sign-off, its receipt or a chain proof entry."""

    model_config = ConfigDict(extra="forbid")

    key_id: str
    algorithm: Literal["ed25519"] = "ed25519"
    public_key: str  # base64 of the 32 raw Ed25519 public key bytes


class RmfSignature(BaseModel):
    """An Ed25519 signature over ``rmf_signing_message(sha256_hash)``."""

    model_config = ConfigDict(extra="forbid")

    key_id: str
    algorithm: Literal["ed25519"] = "ed25519"
    signed_at: datetime  # not part of the signed message
    signature: str  # base64 of the 64 raw Ed25519 signature bytes


class SignOff(BaseModel):
    """An approver's decision on one register version, made in RiskForge Team.

    ``signature`` signs every other field, ``key_id`` and ``comment`` included
    (``riskforge.integrity.rmf.signoff_signing_message``). The free CLI does not
    create sign-offs.
    """

    model_config = ConfigDict(extra="forbid")

    approver: str
    decision: Literal["approved", "rejected", "changes_requested"]
    comment: str = ""
    version_number: int = Field(..., ge=1)
    register_fingerprint: str
    totp_verified_at: datetime
    signed_at: datetime
    key_id: str
    signature: str


class ChainProof(BaseModel):
    """Every entry of the project chain up to the export (ADR-04 section 6)."""

    model_config = ConfigDict(extra="forbid")

    scope: Literal["project", "system"]
    entries: list[AuditEntry]

    @field_serializer("entries", mode="plain")
    def _entries_as_stored(self, entries: list[AuditEntry]) -> list[dict]:
        # Each entry exactly as audit.jsonl stores and hashes it: unset optional fields
        # are left out, so the entry hashes check from the file alone.
        from riskforge.integrity.chain import entry_to_dict

        return [entry_to_dict(entry) for entry in entries]


class RiskManagementFile(BaseModel):
    """
    The Article 9 / Annex IV output artefact.

    Bundles the RiskRegister with derived test requirements and cross-references.
    ``sha256_hash`` is the content digest (``riskforge.integrity.rmf.content_digest``),
    which leaves out ``id``, ``generated_at`` and the provenance blocks ``signatures``,
    ``public_keys``, ``chain_proof`` and ``receipt``.
    """

    model_config = {"populate_by_name": True}

    id: UUID = Field(default_factory=uuid4)
    rmf_schema_version: str = RMF_SCHEMA_VERSION
    risk_register: RiskRegister = Field(alias="register", serialization_alias="register")

    @property
    def register(self) -> RiskRegister:
        """Convenience alias for risk_register, matching the JSON key."""
        return self.risk_register

    test_requirements: list[TestRequirement] = Field(default_factory=list)
    cross_references: list[CrossReference] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sha256_hash: str = ""
    disclosure: str = (
        "This document was produced using RiskForge. "
        "It represents the team's documented risk assessment and has "
        "not been reviewed by a qualified legal professional. "
        "It does not constitute legal advice under the EU AI Act or any other regulation."
    )
    signoffs: list[SignOff] = Field(default_factory=list)
    signatures: list[RmfSignature] = Field(default_factory=list)
    public_keys: list[PublicKeyRecord] = Field(default_factory=list)
    chain_proof: ChainProof | None = None
    receipt: Receipt | None = None

    @model_serializer(mode="wrap")
    def _provenance_as_written(self, handler: SerializerFunctionWrapHandler) -> Any:
        # An unset chain proof or receipt is left out rather than written as null, and a
        # receipt is written as `riskforge receipt` writes it: signing fields only when
        # it is signed.
        data = handler(self)
        if not isinstance(data, dict):
            return data
        if self.chain_proof is None:
            data.pop("chain_proof", None)
        if self.receipt is None:
            data.pop("receipt", None)
        elif isinstance(data.get("receipt"), dict):
            from riskforge.integrity.receipts import SIGNING_FIELDS

            for name in SIGNING_FIELDS:
                if data["receipt"].get(name) is None:
                    data["receipt"].pop(name, None)
        return data


def rmf_document(rmf: RiskManagementFile) -> dict:
    """The JSON document RiskForge writes for ``rmf``, as RMF schema 1.1.0 describes it."""
    return rmf.model_dump(mode="json", by_alias=True)
