"""Unit tests for the AuditEngine hash chain and FileStore verify_chain."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from riskforge.engine.audit import AuditEngine
from riskforge.engine.integrity import IntegrityError
from riskforge.engine.risk import RiskEngine
from riskforge.models.audit import AuditActor
from riskforge.models.register import RiskRegister
from riskforge.models.risk import Likelihood, RiskDimension, RiskItem, Severity
from riskforge.models.system import AISystem, AnnexIIICategory
from riskforge.storage.filesystem import FileStore


def _make_system() -> AISystem:
    return AISystem(
        name="Test System",
        version="1.0",
        purpose="Unit test AI system for audit chain testing.",
        provider_name="AiExponent",
        annex_iii_category=AnnexIIICategory.essential_services,
    )


def _make_item(i: int = 0) -> RiskItem:
    return RiskItem(
        dimension=RiskDimension.privacy,
        title=f"Risk {i}",
        description="Desc.",
        source="manual",
        likelihood=Likelihood.possible,
        severity=Severity.moderate,
        residual_likelihood=Likelihood.unlikely,
        residual_severity=Severity.minor,
    )


async def _bootstrap(store: FileStore, system: AISystem) -> str:
    """Init project, write system + register, return system_id."""
    sid = str(system.id)
    await store.init_project("proj-001", {"system_name": system.name})
    await store.write_system(sid, system)
    reg = RiskRegister(
        system=system,
        assessor_name="Alice",
        assessor_role="Lead",
        assessment_date=datetime.now(UTC),
        review_date=datetime.now(UTC) + timedelta(days=365),
        question_bank_version="1.0.0",
    )
    await store.write_register(sid, reg)
    return sid


@pytest.mark.asyncio
async def test_empty_audit_chain_is_valid(tmp_path: Path) -> None:
    """An empty audit log is considered valid."""
    store = FileStore(tmp_path)
    await store.init_project("p", {})
    valid, violations = await store.verify_chain()
    assert valid
    assert violations == []


@pytest.mark.asyncio
async def test_audit_chain_valid_after_multiple_writes(tmp_path: Path) -> None:
    """Adding several risk items must produce a valid hash chain."""
    store = FileStore(tmp_path)
    sys = _make_system()
    sid = await _bootstrap(store, sys)

    actor = AuditActor(type="human", identity="alice@test.com")
    audit = AuditEngine(store, actor)
    engine = RiskEngine(store, audit)

    for i in range(5):
        await engine.add_risk(sid, _make_item(i))

    valid, violations = await store.verify_chain()
    assert valid, f"Chain invalid: {violations}"
    assert violations == []


@pytest.mark.asyncio
async def test_tampered_entry_detected(tmp_path: Path) -> None:
    """Modifying a stored audit entry must make verify_chain fail."""
    store = FileStore(tmp_path)
    sys = _make_system()
    sid = await _bootstrap(store, sys)

    actor = AuditActor(type="human", identity="alice@test.com")
    audit = AuditEngine(store, actor)
    engine = RiskEngine(store, audit)
    await engine.add_risk(sid, _make_item(0))

    # Tamper: change the event field in the first entry
    audit_path = store._audit_path
    lines = audit_path.read_text().splitlines()
    raw = json.loads(lines[0])
    raw["event"] = "tampered_event"
    lines[0] = json.dumps(raw)
    audit_path.write_text("\n".join(lines) + "\n")

    valid, violations = await store.verify_chain()
    assert not valid
    assert any("entry_hash mismatch" in v for v in violations)


@pytest.mark.asyncio
async def test_seq_numbering_starts_at_zero(tmp_path: Path) -> None:
    """First audit entry must have seq=0 and prev_hash='0000000000'."""
    store = FileStore(tmp_path)
    sys = _make_system()
    sid = await _bootstrap(store, sys)

    actor = AuditActor(type="human", identity="tester")
    audit = AuditEngine(store, actor)
    engine = RiskEngine(store, audit)
    await engine.add_risk(sid, _make_item(0))

    entries = [e async for e in store.read_audit()]
    assert len(entries) == 1
    assert entries[0].seq == 0
    assert entries[0].prev_hash == "0000000000"


def test_assess_engine_loads_all_dimensions() -> None:
    """AssessEngine loads questions for all 8 dimensions from the question bank."""
    import riskforge._data as _data_pkg
    from riskforge.engine.assess import AssessEngine

    data_dir = Path(_data_pkg.__file__).parent
    engine = AssessEngine(data_dir)

    for dim in RiskDimension:
        questions = engine.load_questions(dim)
        assert len(questions) > 0, f"No questions found for dimension {dim.value}"
        for q in questions:
            assert "id" in q, f"Question missing 'id' in {dim.value}"
            assert "text" in q, f"Question missing 'text' in {dim.value}"


def test_assess_engine_question_to_risk_item() -> None:
    """question_to_risk_item produces a correctly scored RiskItem."""
    import riskforge._data as _data_pkg
    from riskforge.engine.assess import AssessEngine

    data_dir = Path(_data_pkg.__file__).parent
    engine = AssessEngine(data_dir)
    questions = engine.load_questions(RiskDimension.privacy)
    q = questions[0]

    item = engine.question_to_risk_item(q, RiskDimension.privacy, 3, 4, answer_unknown=False)
    assert item.dimension == RiskDimension.privacy
    assert item.likelihood == 3
    assert item.severity == 4
    assert item.risk_score == 12
    assert item.risk_band == "high"
    assert not item.knowledge_gap
    assert item.source == "question_bank"


def test_assess_engine_knowledge_gap_flag() -> None:
    """Questions answered 'unknown' must set knowledge_gap=True."""
    import riskforge._data as _data_pkg
    from riskforge.engine.assess import AssessEngine

    data_dir = Path(_data_pkg.__file__).parent
    engine = AssessEngine(data_dir)
    questions = engine.load_questions(RiskDimension.discrimination)
    q = questions[0]

    item = engine.question_to_risk_item(q, RiskDimension.discrimination, 2, 3, answer_unknown=True)
    assert item.knowledge_gap is True


@pytest.mark.asyncio
async def test_record_rejects_tampered_tail(tmp_path: Path) -> None:
    """A record onto a chain whose tail entry was tampered is refused, and appends nothing."""
    store = FileStore(tmp_path)
    sid = await _bootstrap(store, _make_system())
    audit = AuditEngine(store, AuditActor(type="human", identity="tester"))
    engine = RiskEngine(store, audit)
    await engine.add_risk(sid, _make_item(0))

    audit_path = store._audit_path
    lines = audit_path.read_text().splitlines()
    raw = json.loads(lines[-1])
    raw["event"] = "tampered_event"
    lines[-1] = json.dumps(raw)
    audit_path.write_text("\n".join(lines) + "\n")

    tampered = audit_path.read_bytes()
    with pytest.raises(IntegrityError, match="entry_hash mismatch"):
        await audit.record("risk_item.created", sid, {})
    assert audit_path.read_bytes() == tampered
