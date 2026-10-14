"""Engine changes and their audit entries commit together (PRD-331)."""

from __future__ import annotations

from pathlib import Path

import pytest
from riskforge.engine.audit import AuditEngine
from riskforge.engine.risk import RiskEngine
from riskforge.engine.system import SystemEngine
from riskforge.models.audit import AuditActor
from riskforge.models.risk import Likelihood, Mitigation, RiskDimension, RiskItem, Severity
from riskforge.models.system import AISystem, AnnexIIICategory
from riskforge.storage.filesystem import FileStore


async def _setup(tmp_path: Path) -> tuple[FileStore, AuditEngine, AISystem]:
    store = FileStore(tmp_path)
    await store.init_project("p", {})
    audit = AuditEngine(store, AuditActor(type="human", identity="t"))
    system = AISystem(name="S", version="1", purpose="hiring", provider_name="P")
    await SystemEngine(store, audit).create(system)
    return store, audit, system


async def _events(store: FileStore) -> list[str]:
    return [entry.event async for entry in store.read_audit()]


def _item(score: int = 2) -> RiskItem:
    return RiskItem(
        dimension=RiskDimension.privacy,
        title="r",
        description="d",
        likelihood=Likelihood(score),
        severity=Severity(score),
        residual_likelihood=Likelihood(score),
        residual_severity=Severity(score),
    )


async def test_create_records_system_created(tmp_path: Path) -> None:
    store, _audit, system = await _setup(tmp_path)
    assert await _events(store) == ["system.created"]
    assert (await store.read_system(str(system.id))).name == "S"
    entry = await store.read_last_audit_entry()
    assert entry.payload == {"name": "S", "version": "1", "annex_iii_category": None}


async def test_classify_updates_system_and_register_with_one_entry(tmp_path: Path) -> None:
    store, audit, system = await _setup(tmp_path)
    sid = str(system.id)
    await RiskEngine(store, audit).create_register(sid, "A", "B")
    await SystemEngine(store, audit).classify(sid, AnnexIIICategory.employment)
    stored = await store.read_system(sid)
    embedded = (await store.read_register(sid)).system
    for record in (stored, embedded):
        assert record.annex_iii_self_classification_documented is True
        assert record.annex_iii_category == AnnexIIICategory.employment
    assert await _events(store) == ["system.created", "register.created", "system.classified"]


async def test_create_register_is_recorded_once(tmp_path: Path) -> None:
    store, audit, system = await _setup(tmp_path)
    engine = RiskEngine(store, audit)
    _first, created_first = await engine.create_register(str(system.id), "A", "B")
    second, created_second = await engine.create_register(str(system.id), "C", "D")
    assert created_first and not created_second
    assert second.assessor_name == "A"
    assert (await _events(store)).count("register.created") == 1


async def test_failed_audit_append_leaves_the_register_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, audit, system = await _setup(tmp_path)
    sid = str(system.id)
    engine = RiskEngine(store, audit)
    await engine.create_register(sid, "A", "B")
    kept = await engine.add_risk(sid, _item(4))
    before = await store.read_register_document(sid)

    async def disk_full(entry):
        raise OSError("disk full")

    monkeypatch.setattr(store, "append_audit", disk_full)
    mitigation = Mitigation(
        description="Encrypt at rest", control_type="preventive", owner="o", status="planned"
    )
    attempts = [
        engine.add_risk(sid, _item()),
        engine.update_risk(sid, kept.model_copy(update={"title": "changed"})),
        engine.accept_risk(sid, str(kept.id), "Residual is tolerable.", "t"),
        engine.add_mitigation(sid, str(kept.id), mitigation, 1, 1),
    ]
    for attempt in attempts:
        with pytest.raises(OSError, match="disk full"):
            await attempt
        assert await store.read_register_document(sid) == before
    assert not list(tmp_path.rglob("*.pending"))
    assert (await _events(store))[-1] == "risk_item.created"
