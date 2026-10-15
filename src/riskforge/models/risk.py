"""RiskItem, Mitigation, Likelihood, Severity, RiskDimension models."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import Enum, IntEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    Field,
    SerializerFunctionWrapHandler,
    computed_field,
    model_serializer,
)

VAGUE_PHRASES = frozenset(
    {
        "we'll monitor it",
        "will monitor",
        "to be determined",
        "tbd",
        "n/a",
        "will address later",
        "monitor",
        "ongoing",
        "review",
        "future work",
        "to be confirmed",
        "tbc",
        "see comments",
    }
)

# A specific control can mention a listed phrase ("independent review board approves
# each release"); this much extra text around the phrase marks it as specific.
_SPECIFIC_MARGIN = 20


def is_vague_description(description: str) -> bool:
    """True when a mitigation description is a placeholder rather than a specific control.

    It is vague when it is one of VAGUE_PHRASES, or contains one as a whole phrase and is
    too short for anything specific to surround it. "monitoring" does not match "monitor".
    """
    text = " ".join(description.lower().split()).strip(" .!")
    if text in VAGUE_PHRASES:
        return True
    return any(
        len(text) < len(phrase) + _SPECIFIC_MARGIN
        and re.search(rf"(?<![\w']){re.escape(phrase)}(?![\w'])", text) is not None
        for phrase in VAGUE_PHRASES
    )


class Likelihood(IntEnum):
    rare = 1
    unlikely = 2
    possible = 3
    likely = 4
    almost_certain = 5


class Severity(IntEnum):
    negligible = 1
    minor = 2
    moderate = 3
    major = 4
    critical = 5


class RiskDimension(str, Enum):
    health_safety = "health_safety"
    fundamental_rights = "fundamental_rights"
    discrimination = "discrimination"
    privacy = "privacy"
    transparency = "transparency"
    human_oversight = "human_oversight"
    robustness = "robustness"
    data_governance = "data_governance"
    # 8 dimensions only — matches the question bank YAML files and PRD spec


def _drop_when_none(data: Any, key: str, value: object) -> Any:
    """Leave an unset optional field out of the dump.

    Registers written before the field existed then dump back byte for byte, and the
    RMF 1.0.0 schema, which does not allow the field, still validates.
    """
    if value is None and isinstance(data, dict):
        data.pop(key, None)
    return data


class Mitigation(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    description: str
    control_type: Literal["preventive", "detective", "corrective"]
    owner: str
    status: Literal["planned", "implemented", "verified"]
    evidence_refs: list[str] = Field(default_factory=list)
    is_vague: bool = False  # auto-flagged if description is generic
    article_ref: str = ""
    nist_rmf_ref: str = ""
    # Self-declared name of whoever recorded the mitigation (PRD-356); not verified.
    recorded_by: str | None = None

    @model_serializer(mode="wrap")
    def _omit_unset_recorded_by(self, handler: SerializerFunctionWrapHandler) -> Any:
        return _drop_when_none(handler(self), "recorded_by", self.recorded_by)

    @property
    def description_is_vague(self) -> bool:
        """True if the description is a known vague placeholder."""
        return is_vague_description(self.description)


class RiskItem(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    dimension: RiskDimension
    title: str
    description: str
    source: Literal["manual", "question_bank", "pattern", "traceforge", "rag_benchmarking"] = (
        "manual"
    )
    likelihood: Likelihood
    severity: Severity
    mitigations: list[Mitigation] = Field(default_factory=list)
    residual_likelihood: Likelihood
    residual_severity: Severity
    accepted: bool = False
    acceptance_rationale: str = ""
    # Self-declared name of whoever accepted the risk (PRD-356); not verified.
    accepted_by: str | None = None
    identified_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    article_refs: list[str] = Field(default_factory=list)  # e.g. ["Art.9(2)(a)", "Art.14"]
    nist_rmf_refs: list[str] = Field(default_factory=list)  # e.g. ["MANAGE 1.3"]
    iso42001_refs: list[str] = Field(default_factory=list)  # e.g. ["Clause 8.4"]
    nist_rmf_ref: str = ""  # legacy single-ref field; prefer nist_rmf_refs
    iso42001_ref: str = ""  # legacy single-ref field; prefer iso42001_refs
    regulatory_status: Literal["settled", "pending_implementing_act"] = "settled"
    knowledge_gap: bool = False  # true when source answer was "unknown"
    knowledge_gap_reason: str = ""
    source_ref: str = ""  # e.g. "rag:pipeline_001", "traceforge:lineage_042"
    tags: list[str] = Field(default_factory=list)
    notes: str = ""

    @model_serializer(mode="wrap")
    def _omit_unset_accepted_by(self, handler: SerializerFunctionWrapHandler) -> Any:
        return _drop_when_none(handler(self), "accepted_by", self.accepted_by)

    @computed_field
    @property
    def risk_score(self) -> int:
        return int(self.likelihood) * int(self.severity)

    @computed_field
    @property
    def residual_risk_score(self) -> int:
        return int(self.residual_likelihood) * int(self.residual_severity)

    @computed_field
    @property
    def risk_band(self) -> Literal["low", "medium", "high", "critical"]:
        s = self.risk_score
        if s <= 4:
            return "low"
        if s <= 9:
            return "medium"
        if s <= 16:
            return "high"
        return "critical"

    @computed_field
    @property
    def residual_risk_band(self) -> Literal["low", "medium", "high", "critical"]:
        s = self.residual_risk_score
        if s <= 4:
            return "low"
        if s <= 9:
            return "medium"
        if s <= 16:
            return "high"
        return "critical"
