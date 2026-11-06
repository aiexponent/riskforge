"""tests generate: deterministic ids, saved on the register as an audited change, checked by G4."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid5

from riskforge.engine.audit import AuditEngine
from riskforge.engine.risk import RiskEngine
from riskforge.engine.tests import TEST_ID_NAMESPACE, TestDerivationEngine
from riskforge.engine.validate import GateResult, GateStatus, ValidateEngine
from riskforge.models.audit import AuditActor
from riskforge.models.register import RiskRegister
from riskforge.models.risk import Likelihood, RiskDimension, RiskItem, Severity
from riskforge.models.system import AISystem
from riskforge.storage.filesystem import FileStore


def _gap(title: str = "Unknown bias") -> RiskItem:
    return RiskItem(
        dimension=RiskDimension.discrimination,
        title=title,
        description="d",
        likelihood=Likelihood(3),
        severity=Severity(3),
        residual_likelihood=Likelihood(3),
        residual_severity=Severity(3),
        knowledge_gap=True,
        tags=["DI-002"],
        source="question_bank",
    )


def _system() -> AISystem:
    return AISystem(name="S", version="1", purpose="p", provider_name="P")


def _register(items: list[RiskItem]) -> RiskRegister:
    now = datetime.now(UTC)
    return RiskRegister(
        system=_system(),
        items=items,
        assessor_name="A",
        assessor_role="B",
        assessment_date=now,
        review_date=now + timedelta(days=365),
    )


def _g4(register: RiskRegister) -> GateResult:
    return next(r for r in ValidateEngine().run(register) if r.gate_id == "G4")


def test_derivation_is_deterministic() -> None:
    items = [_gap()]
    first = TestDerivationEngine().derive(items)
    second = TestDerivationEngine().derive(items)
    assert first
    assert first == second


def test_requirement_id_is_uuid5_of_item_and_metric() -> None:
    item = _gap()
    (requirement,) = TestDerivationEngine().derive([item])
    assert requirement.id == uuid5(TEST_ID_NAMESPACE, f"{item.id}:{requirement.metric_type}")


def _item(dimension: RiskDimension, tags: list[str], source: str) -> RiskItem:
    return RiskItem(
        dimension=dimension,
        title="A risk",
        description="d",
        likelihood=Likelihood(3),
        severity=Severity(3),
        residual_likelihood=Likelihood(3),
        residual_severity=Severity(3),
        knowledge_gap=True,
        tags=tags,
        source=source,
    )


def test_every_requirement_cites_article_9_8_and_leaves_the_threshold_to_the_provider() -> None:
    """D5 of the 2.0.0 independent test: entries cited Art.9(2)(a), 9(2)(b), 10, 13 and 14
    under a heading for Article 9(6) to 9(8), with thresholds the tool made up."""
    items = [_item(dimension, [], "manual") for dimension in RiskDimension]
    items += [_item(RiskDimension.privacy, ["PR-004"], "question_bank")]
    requirements = TestDerivationEngine().derive(items)
    assert len(requirements) == len(items)
    assert {r.article_ref for r in requirements} == {"Art.9(8)"}
    assert {r.threshold_range for r in requirements} == {"set by the provider before testing"}


def test_a_bank_item_gets_its_question_metric() -> None:
    """The four robustness risks of a tabular model all got `faithfulness`, a metric for
    generated text, and reviewer training got `override_latency_ms` (D5)."""
    training = _item(RiskDimension.human_oversight, ["HO-002"], "question_bank")
    floor = _item(RiskDimension.robustness, ["RO-003"], "question_bank")
    by_item = {r.risk_item_id: r for r in TestDerivationEngine().derive([training, floor])}
    assert by_item[training.id].metric_type == "reviewer_training_coverage"
    assert by_item[floor.id].metric_type == "floor_breach_response_time_min"
    assert by_item[training.id].description == (
        "Risk: A risk. Measure: Share of human reviewers trained on the system's "
        "capabilities, limitations and known biases. Set the threshold before testing, "
        "appropriate to the intended purpose."
    )


def test_an_item_without_a_bank_question_gets_its_dimension_metric() -> None:
    pattern = _item(RiskDimension.robustness, ["pattern:CREDIT_SCORING_BIAS"], "pattern")
    unknown = _item(RiskDimension.robustness, ["ZZ-999"], "question_bank")
    metrics = {r.metric_type for r in TestDerivationEngine().derive([pattern, unknown])}
    assert metrics == {"stress_set_accuracy"}


def test_no_metric_is_one_the_independent_test_found_undefined_or_misapplied() -> None:
    items = [_item(dimension, [], "manual") for dimension in RiskDimension]
    metrics = {r.metric_type for r in TestDerivationEngine().derive(items)}
    assert not metrics & {"faithfulness", "answer_relevance", "fundamental_rights_impact_score"}


def test_a_title_that_ends_a_sentence_gets_no_second_stop() -> None:
    item = _item(RiskDimension.privacy, [], "manual")
    item.title = "Is personal data minimised?"
    [requirement] = TestDerivationEngine().derive([item])
    assert requirement.description.startswith("Risk: Is personal data minimised? Measure:")


def test_g4_warns_until_every_gap_has_a_saved_requirement() -> None:
    first, second = _gap("one"), _gap("two")
    register = _register([first, second])
    g4 = _g4(register)
    assert g4.status == GateStatus.WARN
    assert "2 knowledge gap(s)" in g4.details

    register.test_requirements = TestDerivationEngine().derive([first])
    g4 = _g4(register)
    assert g4.status == GateStatus.WARN
    assert "1 knowledge gap(s)" in g4.details
    assert str(second.id)[:8] in g4.details

    register.test_requirements = TestDerivationEngine().derive(register.items)
    assert _g4(register).status == GateStatus.PASS


def test_g4_passes_without_knowledge_gaps() -> None:
    assert _g4(_register([])).status == GateStatus.PASS


async def test_saving_twice_records_once(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    await store.init_project("p", {})
    system = _system()
    sid = str(system.id)
    await store.write_system(sid, system)
    audit = AuditEngine(store, AuditActor(type="human", identity="t"))
    engine = RiskEngine(store, audit)
    await engine.create_register(sid, "A", "B")
    item = await engine.add_risk(sid, _gap())

    requirements = TestDerivationEngine().derive((await store.read_register(sid)).items)
    assert await engine.set_test_requirements(sid, requirements) is True
    assert await engine.set_test_requirements(sid, requirements) is False

    entries = [entry async for entry in store.read_audit()]
    generated = [entry for entry in entries if entry.event == "tests.generated"]
    assert len(generated) == 1
    assert generated[0].payload == {"count": 1, "risk_item_ids": [str(item.id)]}
    assert (await store.read_register(sid)).test_requirements == requirements


def test_g4_warns_when_saved_requirements_are_out_of_date() -> None:
    gap = _gap()
    register = _register([gap])
    register.test_requirements = TestDerivationEngine().derive(register.items)
    assert _g4(register).status == GateStatus.PASS

    high = _gap("High score, no gap")
    high.knowledge_gap = False
    high.likelihood = high.residual_likelihood = Likelihood(4)
    high.severity = high.residual_severity = Severity(4)
    register.items.append(high)
    g4 = _g4(register)
    assert g4.status == GateStatus.WARN
    assert "out of date" in g4.details


def test_a_dimension_metric_named_like_a_bank_metric_measures_the_same_thing() -> None:
    from riskforge.engine.tests import DIMENSION_METRIC_HINTS, question_metrics

    by_name = {m["metric_type"]: m["measure"] for m in question_metrics().values()}
    for metric in DIMENSION_METRIC_HINTS.values():
        assert by_name.get(metric["metric_type"], metric["measure"]) == metric["measure"]
