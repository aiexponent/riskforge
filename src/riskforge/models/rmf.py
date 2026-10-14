"""RiskManagementFile — the Article 9 / Annex IV export artefact."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, SerializerFunctionWrapHandler, model_serializer

from riskforge.models.register import RiskRegister


class CrossReference(BaseModel):
    """Maps a cluster of risk items to regulatory and framework references."""

    article_ref: str  # e.g. "Art.9(2)(a)"
    risk_item_ids: list[UUID]
    nist_rmf_ref: str = ""  # e.g. "MAP 1.1"
    iso42001_ref: str = ""  # e.g. "Clause 6.1"


class TestRequirement(BaseModel):
    """A measurable test/evaluation requirement derived from a risk item."""

    id: UUID = Field(default_factory=uuid4)
    risk_item_id: UUID
    description: str
    metric_type: str  # e.g. "demographic_parity", "faithfulness", "adversarial_accuracy"
    threshold_range: str  # e.g. ">= 0.85", "<= 0.05", "[0.80, 1.00]"
    article_ref: str = ""  # e.g. "Art.9(7)"
    nist_rmf_ref: str = ""  # e.g. "MEASURE 2.5"


class RiskManagementFile(BaseModel):
    """
    The Article 9 / Annex IV output artefact.

    Bundles the RiskRegister with derived test requirements, cross-references,
    and integrity metadata (SHA-256 hash and optional digital signature).
    Self-verifying via sha256_hash.
    """

    model_config = {"populate_by_name": True}

    id: UUID = Field(default_factory=uuid4)
    rmf_schema_version: str = "1.0.0"
    risk_register: RiskRegister = Field(alias="register", serialization_alias="register")

    @property
    def register(self) -> RiskRegister:
        """Convenience alias for risk_register — matches the JSON serialisation key."""
        return self.risk_register

    test_requirements: list[TestRequirement] = Field(default_factory=list)
    cross_references: list[CrossReference] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sha256_hash: str = ""  # computed over canonical JSON with this field = ""
    signed_by: str = ""  # optional Sigstore/PGP signer identity
    audit_entry_hash: str = ""  # hash of the rmf.exported audit log entry
    disclosure: str = (
        "This document was produced using RiskForge. "
        "It represents the team's documented risk assessment and has "
        "not been reviewed by a qualified legal professional. "
        "It does not constitute legal advice under the EU AI Act or any other regulation."
    )

    @model_serializer(mode="wrap")
    def _fit_schema_1_0_0(self, handler: SerializerFunctionWrapHandler) -> Any:
        """Leave out the fields RMF schema 1.0.0 does not allow.

        ``accepted_by`` and ``recorded_by`` (PRD-356) stay on the register, so the
        Markdown and PDF exports show them, but schema 1.0.0 forbids extra properties.
        RMF schema 1.1.0 (PRD-338) adds them to the JSON export.
        """
        data = handler(self)
        register = (
            data.get("register", data.get("risk_register")) if isinstance(data, dict) else None
        )
        for item in (register or {}).get("items", []):
            item.pop("accepted_by", None)
            for mitigation in item.get("mitigations", []):
                mitigation.pop("recorded_by", None)
        return data
