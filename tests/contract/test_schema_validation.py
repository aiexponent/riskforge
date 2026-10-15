"""Contract tests: every export path must validate against RMF schema 1.1.0."""

from __future__ import annotations

import datetime

import jsonschema
import pytest
from riskforge.integrity.rmf import content_digest, load_schema
from riskforge.models.register import RiskRegister
from riskforge.models.risk import Likelihood, RiskDimension, RiskItem, Severity
from riskforge.models.rmf import RiskManagementFile, rmf_document
from riskforge.models.system import AISystem, AnnexIIICategory


@pytest.fixture
def schema() -> dict:
    return load_schema("1.1.0")


def minimal_rmf() -> RiskManagementFile:
    system = AISystem(
        name="Fraud Detector",
        version="1.2",
        purpose="Detect fraudulent transactions in real time.",
        provider_name="AI Exponent LLC",
        annex_iii_category=AnnexIIICategory.essential_services,
        annex_iii_self_classification_documented=True,
    )
    item = RiskItem(
        dimension=RiskDimension.robustness,
        title="Model accuracy below threshold",
        description="Accuracy on minority class falls below 85% in production.",
        source="manual",
        likelihood=Likelihood.possible,
        severity=Severity.major,
        residual_likelihood=Likelihood.unlikely,
        residual_severity=Severity.moderate,
    )
    register = RiskRegister(
        system=system,
        items=[item],
        assessor_name="Alice Wong",
        assessor_role="AI Governance Lead",
        assessment_date=datetime.datetime.now(datetime.UTC),
        review_date=datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=365),
        question_bank_version="1.0.0",
    )
    rmf = RiskManagementFile(register=register)
    rmf.sha256_hash = content_digest(rmf_document(rmf))
    return rmf


def test_minimal_rmf_passes_schema(schema: dict) -> None:
    rmf = minimal_rmf()
    data = rmf_document(rmf)
    # Should not raise
    jsonschema.validate(data, schema)


def test_schema_has_correct_id(schema: dict) -> None:
    assert schema["$id"] == "https://aiexponent.com/schemas/riskforge/rmf/1.1.0.json"


def test_schema_requires_sha256_hash(schema: dict) -> None:
    assert "sha256_hash" in schema["required"]


def test_rmf_without_register_fails_schema(schema: dict) -> None:
    data = rmf_document(minimal_rmf())
    del data["register"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(data, schema)


def test_risk_item_invalid_dimension_fails_schema(schema: dict) -> None:
    data = rmf_document(minimal_rmf())
    data["register"]["items"][0]["dimension"] = "invalid_dimension"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(data, schema)
