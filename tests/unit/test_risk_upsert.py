"""RiskEngine.upsert_item matches items by origin (PRD-334)."""

from __future__ import annotations

from pathlib import Path

import pytest
from riskforge.engine.audit import AuditEngine
from riskforge.engine.risk import RiskEngine, duplicate_origins, origin_key
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
    added = await engine.upsert_item(sid, _item("question_bank", ["PR-001"]))
    assert (added.outcome, added.previous, added.matches) == ("added", None, 0)
    entries = len(await _log(store))

    same = await engine.upsert_item(sid, _item("question_bank", ["PR-001"]))
    assert (same.outcome, same.item.id, same.matches) == ("unchanged", added.item.id, 1)
    assert len(await _log(store)) == entries

    updated = await engine.upsert_item(sid, _item("question_bank", ["PR-001"], score=5))
    assert (updated.outcome, updated.item.id) == ("updated", added.item.id)
    assert (updated.previous.likelihood, updated.previous.severity) == (3, 3)
    assert (updated.item.residual_likelihood, updated.item.residual_severity) == (5, 5)
    register = await store.read_register(sid)
    assert len(register.items) == 1
    last = (await _log(store))[-1]
    assert last.event == "risk_item.updated"
    assert last.payload["reason"] == "reassessment"


async def test_reassessment_payload_names_old_and_new_values(tmp_path: Path) -> None:
    engine, store, sid = await _engine(tmp_path)
    first = _item("question_bank", ["PR-001"])
    first.likelihood, first.severity = Likelihood(4), Severity(5)
    await engine.upsert_item(sid, first)
    swapped = _item("question_bank", ["PR-001"])
    swapped.likelihood, swapped.severity = Likelihood(5), Severity(4)
    swapped.knowledge_gap = True
    result = await engine.upsert_item(sid, swapped)
    assert result.outcome == "updated"
    payload = (await _log(store))[-1].payload
    assert payload == {
        "risk_item_id": str(result.item.id),
        "old_score": 20,
        "new_score": 20,
        "reason": "reassessment",
        "old_likelihood": 4,
        "new_likelihood": 5,
        "old_severity": 5,
        "new_severity": 4,
        "old_knowledge_gap": False,
        "new_knowledge_gap": True,
    }


async def test_duplicates_are_counted_and_none_is_removed(tmp_path: Path) -> None:
    engine, store, sid = await _engine(tmp_path)
    await engine.add_risk(sid, _item("question_bank", ["PR-001"]))
    await engine.add_risk(sid, _item("question_bank", ["PR-001"]))
    register = await store.read_register(sid)
    assert {key: len(items) for key, items in duplicate_origins(register.items).items()} == {
        "question:PR-001": 2
    }
    result = await engine.upsert_item(sid, _item("question_bank", ["PR-001"], score=5))
    assert (result.outcome, result.matches) == ("updated", 2)
    items = (await store.read_register(sid)).items
    assert [i.likelihood for i in items] == [5, 3]
