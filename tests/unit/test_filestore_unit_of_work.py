"""FileStore unit of work: a change and its audit entry land together or not at all (PRD-331)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import riskforge.storage.filesystem as filesystem
from riskforge.engine.audit import AuditEngine
from riskforge.models.audit import AuditActor
from riskforge.models.register import RiskRegister
from riskforge.models.risk import Likelihood, Mitigation, RiskDimension, RiskItem, Severity
from riskforge.models.system import AISystem
from riskforge.storage.errors import (
    AuditLogCorruptError,
    RegisterNotFoundError,
    SystemNotFoundError,
)
from riskforge.storage.filesystem import FileStore

AWKWARD = [
    "Müller GmbH",
    "line one\nline two: with a colon",
    "yes",
    "null",
    "1.0",
    "  leading and trailing  ",
    'it\'s "quoted"',
    "#not a comment",
    "- not a list",
    "key: value",
]


def _register(system: AISystem, items: list[RiskItem] | None = None) -> RiskRegister:
    now = datetime.now(UTC)
    return RiskRegister(
        system=system,
        items=items or [],
        assessor_name="A",
        assessor_role="B",
        assessment_date=now,
        review_date=now + timedelta(days=365),
    )


async def _project(tmp_path: Path) -> tuple[FileStore, AuditEngine, AISystem]:
    store = FileStore(tmp_path)
    await store.init_project("p", {})
    system = AISystem(name="S", version="1", purpose="p", provider_name="P")
    audit = AuditEngine(store, AuditActor(type="human", identity="t"))
    async with store.unit_of_work():
        await store.write_system(str(system.id), system)
        await audit.record("system.created", str(system.id), {})
    return store, audit, system


async def test_change_and_entry_commit_together(tmp_path: Path) -> None:
    store, audit, system = await _project(tmp_path)
    sid = str(system.id)
    async with store.unit_of_work():
        await store.write_register(sid, _register(system))
        await audit.record("register.created", sid, {})
    assert (await store.read_register(sid)).system.id == system.id
    assert not list(tmp_path.rglob("*.pending"))
    assert not (tmp_path / ".riskforge" / "txn.json").exists()
    head = json.loads((tmp_path / ".riskforge" / "audit.head.json").read_text())
    last = await store.read_last_audit_entry()
    assert head == {"seq": last.seq, "entry_hash": last.entry_hash}


async def test_change_without_an_entry_is_discarded(tmp_path: Path) -> None:
    store, _audit, system = await _project(tmp_path)
    sid = str(system.id)
    with pytest.raises(RuntimeError, match="stop before recording"):
        async with store.unit_of_work():
            await store.write_register(sid, _register(system))
            raise RuntimeError("stop before recording")
    with pytest.raises(RegisterNotFoundError):
        await store.read_register(sid)
    assert not list(tmp_path.rglob("*.pending"))


async def test_system_write_without_an_entry_is_discarded(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    await store.init_project("p", {})
    system = AISystem(name="S", version="1", purpose="p", provider_name="P")
    with pytest.raises(RuntimeError, match="stop before recording"):
        async with store.unit_of_work():
            await store.write_system(str(system.id), system)
            assert await store.list_systems() == []
            raise RuntimeError("stop before recording")
    with pytest.raises(SystemNotFoundError):
        await store.read_system(str(system.id))
    assert await store.list_systems() == []


async def test_reads_inside_a_unit_of_work_see_its_own_writes(tmp_path: Path) -> None:
    store, audit, system = await _project(tmp_path)
    sid = str(system.id)
    async with store.unit_of_work():
        await store.write_register(sid, _register(system))
        assert (await store.read_register(sid)).assessor_name == "A"
        await audit.record("register.created", sid, {})


async def test_nested_unit_of_work_joins_the_outer_one(tmp_path: Path) -> None:
    store, audit, system = await _project(tmp_path)
    sid = str(system.id)
    async with store.unit_of_work():
        async with store.unit_of_work():
            await store.write_register(sid, _register(system))
        await audit.record("register.created", sid, {})
    assert (await store.read_register(sid)).system.id == system.id


async def test_append_outside_a_unit_of_work_is_refused(tmp_path: Path) -> None:
    store, _audit, _system = await _project(tmp_path)
    last = await store.read_last_audit_entry()
    with pytest.raises(RuntimeError, match="unit_of_work"):
        await store.append_audit(last)


async def test_interrupted_commit_is_finished_by_the_next_unit_of_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, audit, system = await _project(tmp_path)
    sid = str(system.id)
    real_replace = os.replace

    def crash_on_pending(src, dst):
        if str(src).endswith(".pending"):
            raise OSError("simulated crash after the audit append")
        return real_replace(src, dst)

    monkeypatch.setattr(filesystem.os, "replace", crash_on_pending)
    with pytest.raises(OSError, match="simulated crash"):
        async with store.unit_of_work():
            await store.write_register(sid, _register(system))
            await audit.record("register.created", sid, {})
    monkeypatch.setattr(filesystem.os, "replace", real_replace)
    async with store.unit_of_work():
        pass
    assert (await store.read_register(sid)).system.id == system.id
    entries = [entry async for entry in store.read_audit()]
    assert entries[-1].event == "register.created"
    head = json.loads((tmp_path / ".riskforge" / "audit.head.json").read_text())
    assert head["seq"] == entries[-1].seq
    assert not (tmp_path / ".riskforge" / "txn.json").exists()


async def test_change_staged_before_a_crash_is_rolled_back(tmp_path: Path) -> None:
    store, _audit, system = await _project(tmp_path)
    sid = str(system.id)
    root = tmp_path / ".riskforge"
    last = await store.read_last_audit_entry()
    pending = root / "systems" / sid / "register.yaml.pending"
    pending.write_text("garbage: true\n")
    (root / "txn.json").write_text(
        json.dumps({"after_seq": last.seq, "files": [f"systems/{sid}/register.yaml"]})
    )
    async with store.unit_of_work():
        pass
    assert not pending.exists()
    assert not (root / "txn.json").exists()
    with pytest.raises(RegisterNotFoundError):
        await store.read_register(sid)


async def test_awkward_text_reads_back_exactly(tmp_path: Path) -> None:
    store, audit, system = await _project(tmp_path)
    sid = str(system.id)
    system.provider_name = "Müller GmbH"
    system.purpose = "line one\nline two"
    items = [
        RiskItem(
            dimension=RiskDimension.privacy,
            title=text,
            description=text,
            likelihood=Likelihood(2),
            severity=Severity(3),
            residual_likelihood=Likelihood(2),
            residual_severity=Severity(3),
            mitigations=[
                Mitigation(
                    description=text, control_type="preventive", owner=text, status="planned"
                )
            ],
        )
        for text in AWKWARD
    ]
    register = _register(system, items)
    async with store.unit_of_work():
        await store.write_register(sid, register)
        await audit.record("register.created", sid, {})
    assert await store.read_register_document(sid) == register.model_dump(mode="json")
    assert (await store.read_register(sid)) == register
    ok, errors = await store.verify_chain()
    assert ok, errors


async def test_read_audit_refuses_a_malformed_line(tmp_path: Path) -> None:
    store, _audit, _system = await _project(tmp_path)
    with (tmp_path / ".riskforge" / "audit.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    with pytest.raises(AuditLogCorruptError):
        [entry async for entry in store.read_audit()]
