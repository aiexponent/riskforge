"""RiskEngine.upsert_item matches items by origin (PRD-334)."""

from __future__ import annotations

from pathlib import Path

import pytest
from riskforge.engine.audit import AuditEngine
from riskforge.engine.risk import RiskEngine, origin_key
from riskforge.engine.system import SystemEngine
from riskforge.models.audit import AuditActor, AuditEntry
from riskforge.models.risk import Likelihood, RiskDimension, RiskItem, Severity
from riskforge.models.system import AISystem, AnnexIIICategory
from riskforge.storage.filesystem import FileStore


def _item(source: str, tags: list[str], title: str = "Risk", score: int = 3) -> RiskItem:
    return RiskItem(
        dimension=RiskDimension.privacy,
        title=title,
        description="Desc.",
        source=source,
        likelihood=Likelihood(score),
        severity=Severity(score),
        residual_likelihood=Likelihood(score),
        residual_severity=Severity(score),
        tags=tags,
    )


async def _engine(tmp_path: Path) -> tuple[RiskEngine, FileStore, str]:
    store = FileStore(tmp_path)
    await store.init_project("proj", {"system_name": "S"})
    audit = AuditEngine(store, AuditActor(type="human", identity="t"))
    system = await SystemEngine(store, audit).create(
        AISystem(
            name="S",
            version="1.0",
            purpose="p",
            provider_name="prov",
            annex_iii_category=AnnexIIICategory.essential_services,
        )
    )
    engine = RiskEngine(store, audit)
    await engine.create_register(str(system.id), "A", "B")
    return engine, store, str(system.id)


async def _log(store: FileStore) -> list[AuditEntry]:
    return [entry async for entry in store.read_audit()]


def test_origin_key() -> None:
    assert origin_key(_item("question_bank", ["PR-001"])) == "question:PR-001"
    assert origin_key(_item("pattern", ["pattern:X"], title="T")) == "pattern:X:T"
    assert origin_key(_item("pattern", ["other"])) is None
    assert origin_key(_item("question_bank", [])) is None
    assert origin_key(_item("manual", ["PR-001"])) is None


async def test_upsert_item_refuses_an_item_with_no_origin(tmp_path: Path) -> None:
    engine, store, sid = await _engine(tmp_path)
    entries = len(await _log(store))
    with pytest.raises(ValueError, match="question bank or a pattern"):
        await engine.upsert_item(sid, _item("manual", []))
    assert (await store.read_register(sid)).items == []
    assert len(await _log(store)) == entries


async def test_upsert_item_adds_updates_and_leaves_unchanged(tmp_path: Path) -> None:
    engine, store, sid = await _engine(tmp_path)
    outcome, added = await engine.upsert_item(sid, _item("question_bank", ["PR-001"]))
    assert outcome == "added"
    entries = len(await _log(store))

    outcome, same = await engine.upsert_item(sid, _item("question_bank", ["PR-001"]))
    assert (outcome, same.id) == ("unchanged", added.id)
    assert len(await _log(store)) == entries

    outcome, updated = await engine.upsert_item(sid, _item("question_bank", ["PR-001"], score=5))
    assert (outcome, updated.id) == ("updated", added.id)
    assert (updated.residual_likelihood, updated.residual_severity) == (5, 5)
    register = await store.read_register(sid)
    assert len(register.items) == 1
    last = (await _log(store))[-1]
    assert last.event == "risk_item.updated"
    assert last.payload["reason"] == "reassessment"
