"""A file changed after a change's integrity check is caught when the change reads it, and
recovery refuses a journal the head file does not fit (PRD-333)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from riskforge.engine.audit import AuditEngine
from riskforge.engine.integrity import IntegrityError, check_integrity
from riskforge.engine.risk import RiskEngine
from riskforge.engine.system import SystemEngine
from riskforge.models.audit import AuditActor
from riskforge.models.risk import Likelihood, RiskDimension, RiskItem, Severity
from riskforge.models.system import AISystem, AnnexIIICategory
from riskforge.storage.errors import StoredFileCorruptError
from riskforge.storage.filesystem import FileStore


def _item(title: str) -> RiskItem:
    return RiskItem(
        dimension=RiskDimension.privacy,
        title=title,
        description="guard probe",
        likelihood=Likelihood(4),
        severity=Severity(4),
        residual_likelihood=Likelihood(4),
        residual_severity=Severity(4),
    )


async def _project(tmp_path: Path) -> tuple[FileStore, AuditEngine, RiskEngine, str]:
    store = FileStore(tmp_path)
    await store.init_project("p", {})
    audit = AuditEngine(store, AuditActor(type="human", identity="t"))
    system = AISystem(name="S", version="1", purpose="p", provider_name="P")
    await SystemEngine(store, audit).create(system)
    engine = RiskEngine(store, audit)
    sid = str(system.id)
    await engine.create_register(sid, "A", "B")
    await engine.add_risk(sid, _item("first"))
    return store, audit, engine, sid


def _register_path(root: Path, sid: str) -> Path:
    return root / ".riskforge" / "systems" / sid / "register.yaml"


def _system_path(root: Path, sid: str) -> Path:
    return root / ".riskforge" / "systems" / sid / "system.yaml"


def _lower_first_score(root: Path, sid: str) -> None:
    path = _register_path(root, sid)
    register = yaml.safe_load(path.read_text(encoding="utf-8"))
    register["items"][0]["likelihood"] = 1
    register["items"][0]["residual_likelihood"] = 1
    path.write_text(yaml.dump(register, sort_keys=False), encoding="utf-8")


def _log(root: Path) -> bytes:
    return (root / ".riskforge" / "audit.jsonl").read_bytes()


# ------------------------------------------------- M1: edits after the check ---- #


async def test_register_edited_after_the_check_is_not_laundered(tmp_path: Path) -> None:
    store, audit, engine, sid = await _project(tmp_path)
    rid = str((await store.read_register(sid)).items[0].id)
    log_before = _log(tmp_path)
    with pytest.raises(IntegrityError, match="changed after"):
        async with audit.unit_of_work():
            _lower_first_score(tmp_path, sid)
            edited = _register_path(tmp_path, sid).read_bytes()
            await engine.accept_risk(sid, rid, "accepted after a swap", "t")
    assert _log(tmp_path) == log_before
    assert _register_path(tmp_path, sid).read_bytes() == edited
    assert not list(tmp_path.rglob("*.pending"))
    assert not (await check_integrity(store)).ok


async def test_register_deleted_after_the_check_is_not_recreated(tmp_path: Path) -> None:
    store, audit, engine, sid = await _project(tmp_path)
    log_before = _log(tmp_path)
    with pytest.raises(IntegrityError, match="register.yaml"):
        async with audit.unit_of_work():
            _register_path(tmp_path, sid).unlink()
            await engine.create_register(sid, "A", "B")
    assert _log(tmp_path) == log_before
    assert not _register_path(tmp_path, sid).exists()


async def test_system_edited_after_the_check_is_not_laundered(tmp_path: Path) -> None:
    store, audit, _engine, sid = await _project(tmp_path)
    log_before = _log(tmp_path)
    with pytest.raises(IntegrityError, match="system.yaml"):
        async with audit.unit_of_work():
            path = _system_path(tmp_path, sid)
            path.write_text(
                path.read_text(encoding="utf-8").replace("name: S", "name: T"), encoding="utf-8"
            )
            await SystemEngine(store, audit).classify(sid, AnnexIIICategory.essential_services)
    assert _log(tmp_path) == log_before


async def test_record_refuses_a_register_it_did_not_write_that_changed(tmp_path: Path) -> None:
    """The export path: the register is read, swapped, then the export is recorded."""
    store, audit, _engine, sid = await _project(tmp_path)
    log_before = _log(tmp_path)
    with pytest.raises(IntegrityError, match="changed after"):
        async with audit.unit_of_work():
            await audit.read_register(sid)
            _lower_first_score(tmp_path, sid)
            await audit.record("rmf.exported", sid, {"format": "json"})
    assert _log(tmp_path) == log_before


async def test_changes_in_one_unit_of_work_still_read_their_own_writes(tmp_path: Path) -> None:
    store, audit, engine, sid = await _project(tmp_path)
    async with audit.unit_of_work():
        for n in range(3):
            await engine.add_risk(sid, _item(f"more {n}"))
        item = (await store.read_register(sid)).items[-1]
        await engine.accept_risk(sid, str(item.id), "within appetite", "t")
        await SystemEngine(store, audit).classify(sid, None)
        await audit.record("rmf.exported", sid, {"format": "json"})
    report = await check_integrity(store)
    assert report.ok, report.errors


async def test_a_second_system_edited_after_the_check_is_not_baselined(tmp_path: Path) -> None:
    from conftest import materialise_v113

    project, sid = materialise_v113(tmp_path / "v113")
    systems = project / ".riskforge" / "systems"
    other = "11111111-2222-4333-8444-555555555555"
    shutil.copytree(systems / sid, systems / other)
    for name in ("system.yaml", "register.yaml"):
        path = systems / other / name
        path.write_text(path.read_text(encoding="utf-8").replace(sid, other), encoding="utf-8")
    store = FileStore(project)
    audit = AuditEngine(store, AuditActor(type="human", identity="t"))
    engine = RiskEngine(store, audit)
    assert (await check_integrity(store)).ok
    log_before = _log(project)
    with pytest.raises(IntegrityError, match=other):
        async with audit.unit_of_work():
            _lower_first_score(project, other)
            await engine.add_risk(sid, _item("after upgrade"))
    assert _log(project) == log_before
    assert b"register.baselined" not in _log(project)


# ------------------------------------- L1: a journal the head file does not fit ---- #


def _plant_torn_journal(root: Path) -> bytes:
    """A journal claiming seq 2 onwards is a torn append, though the head names the end."""
    log = _log(root)
    lines = log.splitlines(keepends=True)
    assert len(lines) >= 4
    journal = {
        "after_seq": 1,
        "log_size": len(b"".join(lines[:2])),
        "count": len(lines) + 1,
        "files": [],
    }
    (root / ".riskforge" / "txn.json").write_text(json.dumps(journal), encoding="utf-8")
    return log


async def test_recovery_refuses_a_journal_the_head_file_does_not_fit(tmp_path: Path) -> None:
    store, _audit, engine, sid = await _project(tmp_path)
    await engine.add_risk(sid, _item("second"))
    log = _plant_torn_journal(tmp_path)
    with pytest.raises(StoredFileCorruptError, match="audit.head.json"):
        await engine.add_risk(sid, _item("third"))
    assert _log(tmp_path) == log
    assert (tmp_path / ".riskforge" / "txn.json").exists()
    with pytest.raises(StoredFileCorruptError, match="audit.head.json"):
        await store.view_after_recovery()


async def test_recovery_still_discards_a_real_torn_append(tmp_path: Path) -> None:
    store, _audit, engine, sid = await _project(tmp_path)
    root = tmp_path / ".riskforge"
    log = _log(tmp_path)
    last = json.loads(log.splitlines()[-1])
    journal = {"after_seq": last["seq"], "log_size": len(log), "count": 1, "files": []}
    (root / "txn.json").write_text(json.dumps(journal), encoding="utf-8")
    with (root / "audit.jsonl").open("ab") as fh:
        fh.write(b'{"seq":')
    view = await store.view_after_recovery()
    assert (await check_integrity(view)).ok
    await engine.add_risk(sid, _item("second"))
    assert _log(tmp_path).startswith(log)
    assert (await check_integrity(store)).ok
