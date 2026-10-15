"""tests generate: deterministic ids, saved on the register as an audited change, checked by G4."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid5

from riskforge.engine.audit import AuditEngine
from riskforge.engine.risk import RiskEngine
from riskforge.engine.tests import DIMENSION_METRIC_HINTS, TEST_ID_NAMESPACE, TestDerivationEngine
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


def test_test_requirements_cite_article_9_8() -> None:
    refs = {hint["article_ref"] for hints in DIMENSION_METRIC_HINTS.values() for hint in hints}
    assert "Art.9(7)" not in refs
    assert "Art.9(8)" in refs


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
