"""Unit tests for ValidateEngine — 8 readiness gates."""

from __future__ import annotations

import datetime

from riskforge.engine.validate import GateStatus, ValidateEngine
from riskforge.models.register import RiskRegister
from riskforge.models.risk import Likelihood, RiskDimension, RiskItem, Severity
from riskforge.models.system import AISystem, AnnexIIICategory


def make_register(
    items: list[RiskItem] | None = None,
    annex_classified: bool = True,
    assessor_name: str = "Alice",
    assessor_role: str = "AI Governance Lead",
) -> RiskRegister:
    system = AISystem(
        name="Test System",
        version="1.0",
        purpose="Test purpose",
        provider_name="AiExponent",
        annex_iii_category=AnnexIIICategory.essential_services,
        annex_iii_self_classification_documented=annex_classified,
    )
    return RiskRegister(
        system=system,
        items=items or [],
        assessor_name=assessor_name,
        assessor_role=assessor_role,
        assessment_date=datetime.datetime.now(datetime.UTC),
        review_date=datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=365),
        question_bank_version="1.0.0",
    )


def make_item(dim: RiskDimension, score: int = 4) -> RiskItem:
    lh = min(score, 5)
    sv = 1
    return RiskItem(
        dimension=dim,
        title=f"Risk in {dim.value}",
        description="Test risk",
        source="manual",
        likelihood=Likelihood(lh),
        severity=Severity(sv),
        residual_likelihood=Likelihood(1),
        residual_severity=Severity(1),
    )


def test_g1_fails_when_dimensions_missing() -> None:
    # Only one dimension present
    register = make_register(items=[make_item(RiskDimension.privacy)])
    engine = ValidateEngine()
    results = engine.run(register)
    g1 = next(r for r in results if r.gate_id == "G1")
    assert g1.status == GateStatus.FAIL
    assert "discrimination" in g1.details


def test_g1_passes_when_all_dimensions_present() -> None:
    items = [make_item(dim) for dim in RiskDimension]
    register = make_register(items=items)
    engine = ValidateEngine()
    results = engine.run(register)
    g1 = next(r for r in results if r.gate_id == "G1")
    assert g1.status == GateStatus.PASS


def test_g2_fails_when_not_classified() -> None:
    register = make_register(annex_classified=False)
    engine = ValidateEngine()
    results = engine.run(register)
    g2 = next(r for r in results if r.gate_id == "G2")
    assert g2.status == GateStatus.FAIL


def test_g6_fails_when_assessor_missing() -> None:
    register = make_register(assessor_name="", assessor_role="")
    engine = ValidateEngine()
    results = engine.run(register)
    g6 = next(r for r in results if r.gate_id == "G6")
    assert g6.status == GateStatus.FAIL


def test_has_failures_returns_true_on_any_fail() -> None:
    register = make_register()  # no items — G1 will fail
    engine = ValidateEngine()
    results = engine.run(register)
    assert engine.has_failures(results) is True


def test_g7_warns_when_all_low_scores() -> None:
    items = [make_item(dim, score=2) for dim in RiskDimension]
    register = make_register(items=items)
    engine = ValidateEngine()
    results = engine.run(register)
    g7 = next(r for r in results if r.gate_id == "G7")
    assert g7.status == GateStatus.WARN


def _g3(item: RiskItem):
    results = ValidateEngine().run(make_register(items=[item]))
    return next(r for r in results if r.gate_id == "G3")


def test_g3_says_what_clears_it() -> None:
    """G3 clears on a residual score at or below the threshold, or acceptance.

    A mitigation recorded without re-scoring the residual does not clear it, so the
    gate's text must not say "mitigated".
    """
    item = make_item(RiskDimension.privacy)
    item.residual_likelihood, item.residual_severity = Likelihood(5), Severity(5)
    failed = _g3(item)
    assert failed.status == GateStatus.FAIL
    for text in (failed.description, failed.details):
        assert "mitigated" not in text
    assert "at or below the risk-appetite threshold" in failed.description
    assert "accepted" in failed.description
    assert "above the risk-appetite threshold and not accepted" in failed.details

    item.accepted = True
    accepted = _g3(item)
    assert accepted.status == GateStatus.PASS
    assert accepted.description == failed.description

    item.accepted = False
    item.residual_likelihood, item.residual_severity = Likelihood(3), Severity(3)
    assert _g3(item).status == GateStatus.PASS
