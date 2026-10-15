"""The engine refuses to change a project that fails its integrity check (PRD-333).

The CLI pre-flight is the first line; these pin the second one: ``AuditEngine`` runs the
check once per outermost unit of work before anything is appended, and never records a
``register.baselined`` entry unless the check passed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import riskforge.engine.integrity as integrity
import yaml
from riskforge.engine.audit import AuditChainCorruptError, AuditEngine
from riskforge.engine.integrity import IntegrityError, IntegrityReport
from riskforge.engine.risk import RiskEngine
from riskforge.engine.system import SystemEngine
from riskforge.models.audit import AuditActor
from riskforge.models.risk import Likelihood, RiskDimension, RiskItem, Severity
from riskforge.models.system import AISystem
from riskforge.storage.filesystem import FileStore


def _item(title: str) -> RiskItem:
    return RiskItem(
        dimension=RiskDimension.privacy,
        title=title,
        description="guard probe",
        likelihood=Likelihood(2),
        severity=Severity(3),
        residual_likelihood=Likelihood(2),
        residual_severity=Severity(3),
    )


async def _project(store: FileStore) -> tuple[AuditEngine, RiskEngine, str]:
    await store.init_project("p", {})
    audit = AuditEngine(store, AuditActor(type="human", identity="t"))
    system = AISystem(name="S", version="1", purpose="p", provider_name="P")
    await SystemEngine(store, audit).create(system)
    engine = RiskEngine(store, audit)
    await engine.create_register(str(system.id), "A", "B")
    await engine.add_risk(str(system.id), _item("first"))
    return audit, engine, str(system.id)


def _riskforge(tmp_path: Path) -> Path:
    return tmp_path / ".riskforge"


def _edit_register(tmp_path: Path, sid: str) -> None:
    path = _riskforge(tmp_path) / "systems" / sid / "register.yaml"
    register = yaml.safe_load(path.read_text(encoding="utf-8"))
    register["items"][0]["likelihood"] = 1
    path.write_text(yaml.dump(register, sort_keys=False), encoding="utf-8")


def _files(tmp_path: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()
    }


async def test_record_refuses_an_edited_register_and_appends_nothing(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    audit, _engine, sid = await _project(store)
    _edit_register(tmp_path, sid)
    before = _files(tmp_path)
    with pytest.raises(IntegrityError, match="changed outside RiskForge") as caught:
        await audit.record("risk.accepted", sid, {})
    assert caught.value.report.errors
    assert _files(tmp_path) == before


async def test_change_refused_before_anything_is_staged(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    _audit, engine, sid = await _project(store)
    _edit_register(tmp_path, sid)
    before = _files(tmp_path)
    with pytest.raises(IntegrityError):
        await engine.add_risk(sid, _item("second"))
    assert _files(tmp_path) == before
    assert not list(tmp_path.rglob("*.pending"))


async def test_deleted_head_file_is_never_baselined(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    _audit, engine, sid = await _project(store)
    _edit_register(tmp_path, sid)
    (_riskforge(tmp_path) / "audit.head.json").unlink()
    log_before = (_riskforge(tmp_path) / "audit.jsonl").read_bytes()
    with pytest.raises(IntegrityError, match="head file"):
        await engine.add_risk(sid, _item("second"))
    log_after = (_riskforge(tmp_path) / "audit.jsonl").read_bytes()
    assert log_after == log_before
    assert b"register.baselined" not in log_after
    assert not (_riskforge(tmp_path) / "audit.head.json").exists()


async def test_one_check_per_outermost_unit_of_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FileStore(tmp_path)
    audit, engine, sid = await _project(store)
    calls = 0
    real_check = integrity.check_integrity

    async def counting_check(storage, **kwargs):  # noqa: ANN001, ANN003, ANN202
        nonlocal calls
        calls += 1
        return await real_check(storage, **kwargs)

    monkeypatch.setattr(integrity, "check_integrity", counting_check)
    async with audit.unit_of_work() as report:
        assert report is not None and report.ok
        for n in range(3):
            await engine.add_risk(sid, _item(f"inner {n}"))
        async with audit.unit_of_work() as nested:
            assert nested is None
    assert calls == 1
    await engine.add_risk(sid, _item("outer a"))
    await engine.add_risk(sid, _item("outer b"))
    assert calls == 3


class _NoStateStore(FileStore):
    """A backend that keeps no unit-of-work state (the StorageBackend default)."""

    def unit_of_work_state(self) -> dict | None:
        return None


async def test_backend_without_state_still_checks_once_per_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _NoStateStore(tmp_path)
    audit, engine, sid = await _project(store)
    calls = 0
    real_check = integrity.check_integrity

    async def counting_check(storage, **kwargs):  # noqa: ANN001, ANN003, ANN202
        nonlocal calls
        calls += 1
        return await real_check(storage, **kwargs)

    monkeypatch.setattr(integrity, "check_integrity", counting_check)
    async with audit.unit_of_work():
        await engine.add_risk(sid, _item("a"))
        await engine.add_risk(sid, _item("b"))
    assert calls == 1
    _edit_register(tmp_path, sid)
    with pytest.raises(IntegrityError):
        await engine.add_risk(sid, _item("c"))
    assert calls == 2


async def test_write_staged_in_a_storage_scope_opened_directly_fails_closed(
    tmp_path: Path,
) -> None:
    """record() checks a scope nobody checked; staged writes in it count as unrecorded."""
    store = FileStore(tmp_path)
    audit, _engine, sid = await _project(store)
    register = await store.read_register(sid)
    register.items.clear()
    before = _files(tmp_path)
    with pytest.raises(IntegrityError):
        async with store.unit_of_work():
            await store.write_register(sid, register)
            await audit.record("register.updated", sid, {})
    assert _files(tmp_path) == before


async def test_untouched_v113_layout_is_baselined_after_the_check(tmp_path: Path) -> None:
    from conftest import materialise_v113

    project, sid = materialise_v113(tmp_path / "v113")
    store = FileStore(project)
    engine = RiskEngine(store, AuditEngine(store, AuditActor(type="human", identity="t")))
    await engine.add_risk(sid, _item("after upgrade"))
    report = await integrity.check_integrity(store)
    assert report.ok, report.errors
    assert report.warnings == []
    head = json.loads((project / ".riskforge" / "audit.head.json").read_text())
    assert head["seq"] == report.entries[-1].seq


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            IntegrityError(IntegrityReport(errors=["first finding.", "second finding."])),
            ["first finding.", "second finding."],
        ),
        (AuditChainCorruptError("Audit chain tail is corrupt."), ["Audit chain tail is corrupt."]),
    ],
)
def test_entry_point_maps_integrity_refusals_to_exit_2(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
    expected: list[str],
) -> None:
    import riskforge.cli.main as main

    def refuse(**_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(main, "app", refuse)
    with pytest.raises(SystemExit) as caught:
        main.run()
    assert caught.value.code == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    lines = err.splitlines()
    for text in expected:
        assert sum(text in line for line in lines) == 1, err


def test_entry_point_still_raises_other_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import riskforge.cli.main as main

    def crash(**_kwargs: object) -> None:
        raise KeyError("not an integrity failure")

    monkeypatch.setattr(main, "app", crash)
    with pytest.raises(KeyError):
        main.run()
