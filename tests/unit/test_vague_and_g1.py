"""Vague mitigation detection uses one whole-phrase list; G1 names a real command (#52)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import riskforge.engine.risk as engine_risk
from riskforge.engine.risk import RiskEngine
from riskforge.engine.validate import ValidateEngine
from riskforge.models.register import RiskRegister
from riskforge.models.risk import (
    Likelihood,
    Mitigation,
    RiskDimension,
    RiskItem,
    Severity,
    is_vague_description,
)
from riskforge.models.system import AISystem

README_EXAMPLE = "Remove postcode feature; add demographic parity monitoring"

CASES = [
    ("we'll monitor it", True),
    ("TBD", True),
    ("Ongoing.", True),
    ("N/A", True),
    ("We will monitor it closely", True),
    ("Monitoring ongoing", True),
    (README_EXAMPLE, False),
    ("independent review board approves each model release", False),
    ("Block release when the demographic parity difference exceeds 0.10; review monthly", False),
]


@pytest.mark.parametrize(("text", "vague"), CASES)
def test_vague_detection_matches_whole_phrases(text: str, vague: bool) -> None:
    assert is_vague_description(text) is vague


@pytest.mark.parametrize(("text", "vague"), CASES)
def test_engine_and_model_agree(text: str, vague: bool) -> None:
    mitigation = Mitigation(
        description=text, control_type="preventive", owner="O", status="planned"
    )
    assert RiskEngine._flag_vague(mitigation).is_vague is vague
    assert mitigation.description_is_vague is vague


def test_engine_keeps_no_second_list() -> None:
    assert not hasattr(engine_risk, "VAGUE_PHRASES")


def _register_with_one_dimension() -> RiskRegister:
    now = datetime.now(UTC)
    system = AISystem(name="S", version="1", purpose="p", provider_name="P")
    item = RiskItem(
        dimension=RiskDimension.privacy,
        title="t",
        description="d",
        likelihood=Likelihood(2),
        severity=Severity(2),
        residual_likelihood=Likelihood(2),
        residual_severity=Severity(2),
    )
    return RiskRegister(
        system=system,
        items=[item],
        assessor_name="A",
        assessor_role="B",
        assessment_date=now,
        review_date=now + timedelta(days=365),
    )


def test_g1_hint_names_a_real_command() -> None:
    register = _register_with_one_dimension()
    g1 = next(r for r in ValidateEngine().run(register) if r.gate_id == "G1")
    assert f"riskforge assess {register.system.id}" in g1.details
    assert "--dimension" in g1.details
    assert "not-applicable" not in g1.details
