"""Regression tests for the RMF model <-> JSON Schema contract.

B1: the Mitigation model emits `article_ref` and `nist_rmf_ref`, but the bundled
`rmf.schema.json` (now `rmf-1.0.0.schema.json`) declared `$defs/Mitigation` with `additionalProperties: false`
and omitted those two fields. Any register containing a mitigation therefore
failed schema validation at export time, blocking JSON/PDF/Markdown export of the
Article 9(2)(d) risk-treatment content. The prior export tests only exercised
mitigation-free registers, so CI stayed green while the core deliverable was broken.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jsonschema
import pytest
from riskforge.integrity.rmf import content_digest, load_schema
from riskforge.models.register import RiskRegister
from riskforge.models.risk import (
    Likelihood,
    Mitigation,
    RiskDimension,
    RiskItem,
    Severity,
)
from riskforge.models.rmf import RiskManagementFile, rmf_document
from riskforge.models.system import AISystem


def _schema() -> dict:
    return load_schema("1.1.0")


def _rmf_with_mitigation() -> RiskManagementFile:
    system = AISystem(
        name="Test System",
        version="1.0",
        purpose="test purpose",
        provider_name="Provider",
        annex_iii_self_classification_documented=True,
    )
    item = RiskItem(
        dimension=RiskDimension.discrimination,
        title="Proxy discrimination",
        description="d",
        source="manual",
        likelihood=Likelihood.likely,
        severity=Severity.major,
        residual_likelihood=Likelihood.unlikely,
        residual_severity=Severity.minor,
        mitigations=[
            Mitigation(
                description="Add demographic parity monitoring on outputs.",
                control_type="detective",
                owner="ML Platform",
                status="implemented",
                article_ref="Art.9(2)(d)",
                nist_rmf_ref="MANAGE 1.3",
            )
        ],
    )
    register = RiskRegister(
        system=system,
        assessor_name="Assessor",
        assessor_role="Role",
        assessment_date=datetime.now(UTC),
        review_date=datetime.now(UTC) + timedelta(days=365),
        question_bank_version="1.0.0",
        items=[item],
    )
    rmf = RiskManagementFile(register=register)
    rmf.sha256_hash = content_digest(rmf_document(rmf))
    return rmf


def test_rmf_with_mitigation_validates_against_schema() -> None:
    """An RMF whose register contains a mitigation must pass schema validation."""
    rmf = _rmf_with_mitigation()
    payload = rmf_document(rmf)
    # Must not raise: the Mitigation's article_ref/nist_rmf_ref are valid fields.
    jsonschema.validate(payload, _schema())


def test_schema_mitigation_allows_model_fields() -> None:
    """Every field the Mitigation model serialises must be permitted by the schema."""
    model_fields = set(
        Mitigation(
            description="x",
            control_type="preventive",
            owner="o",
            status="planned",
        ).model_dump(mode="json")
    )
    mitigation_schema = _schema()["$defs"]["Mitigation"]
    allowed = set(mitigation_schema["properties"])
    assert (
        model_fields <= allowed
    ), f"model emits fields the schema rejects: {model_fields - allowed}"


def test_schema_requires_nonempty_disclosure() -> None:
    """The mandatory disclosure is enforced by the schema, not only injected by the
    export path. A hand-crafted or downstream-tampered RMF that drops or empties the
    disclosure must fail schema validation, so non-removability does not rest solely
    on RiskForge's own export code.
    """
    schema = _schema()
    payload = rmf_document(_rmf_with_mitigation())

    # Baseline: a fully-formed RMF carries a non-empty disclosure and validates.
    assert payload.get("disclosure")
    jsonschema.validate(payload, schema)

    # Disclosure removed -> rejected by `required`.
    without = {k: v for k, v in payload.items() if k != "disclosure"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(without, schema)

    # Disclosure present but empty -> rejected by `minLength`.
    emptied = {**payload, "disclosure": ""}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(emptied, schema)
