"""check_integrity: every row of ADR-03 section 5, the baseline rule and read-only mode (PRD-332)."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from riskforge.engine.audit import AuditEngine
from riskforge.engine.integrity import (
    ChangeInProgressError,
    IntegrityError,
    check_integrity,
    check_integrity_settled,
    latest_fingerprints,
    require_intact,
)
from riskforge.engine.risk import RiskEngine
from riskforge.engine.system import SystemEngine
from riskforge.integrity.canonical import document_fingerprint
from riskforge.integrity.chain import GENESIS_PREV_HASH, compute_entry_hash, entry_to_dict
from riskforge.models.audit import AuditActor, AuditEntry
from riskforge.models.register import RiskRegister
from riskforge.models.risk import Likelihood, RiskDimension, RiskItem, Severity
from riskforge.models.system import AISystem
from riskforge.storage.errors import PendingChangeError
from riskforge.storage.filesystem import FileStore

ACTOR = AuditActor(type="human", identity="t")


def _item(n: int) -> RiskItem:
    return RiskItem(
        dimension=RiskDimension.privacy,
        title=f"r{n}",
        description="d",
        likelihood=Likelihood(4),
        severity=Severity(5),
        residual_likelihood=Likelihood(4),
        residual_severity=Severity(5),
    )


async def _seeded(tmp_path: Path) -> tuple[FileStore, str]:
    store = FileStore(tmp_path)
    await store.init_project("p", {})
    audit = AuditEngine(store, ACTOR)
    system = AISystem(name="S", version="1", purpose="credit scoring", provider_name="P")
    sid = str(system.id)
    await SystemEngine(store, audit).create(system)
    engine = RiskEngine(store, audit)
    await engine.create_register(sid, "A", "B")
    for n in range(3):
        await engine.add_risk(sid, _item(n))
    return store, sid


def _root(project: Path) -> Path:
    return project / ".riskforge"


def _log(project: Path) -> Path:
    return _root(project) / "audit.jsonl"


def _system_dir(project: Path, sid: str) -> Path:
    return _root(project) / "systems" / sid


def _entries(project: Path) -> list[AuditEntry]:
    return [
        AuditEntry.model_validate(json.loads(x)) for x in _log(project).read_text().splitlines()
    ]


def _write_entries(project: Path, entries: list[AuditEntry]) -> None:
    _log(project).write_text(
        "".join(json.dumps(entry_to_dict(e), separators=(",", ":")) + "\n" for e in entries)
    )


def _relink(entries: list[AuditEntry]) -> list[AuditEntry]:
    prev = GENESIS_PREV_HASH
    for seq, entry in enumerate(entries):
        entry.seq = seq
        entry.prev_hash = prev
        entry.entry_hash = compute_entry_hash(entry)
        prev = entry.entry_hash
    return entries


def _dump(document: object) -> str:
    return yaml.dump(document, sort_keys=False, allow_unicode=True)


def _v113_system_files(project: Path, items: int, *, register: bool = True) -> str:
    """A system as RiskForge 1.1.3 left it: files on disk, no audit entry."""
    system = AISystem(name="Other", version="1", purpose="hiring", provider_name="P")
    sid = str(system.id)
    directory = _system_dir(project, sid)
    directory.mkdir(parents=True)
    (directory / "system.yaml").write_text(_dump(system.model_dump(mode="json")))
    if register:
        now = datetime.now(UTC)
        reg = RiskRegister(
            system=system,
            assessor_name="A",
            assessor_role="B",
            assessment_date=now,
            review_date=now,
            items=[_item(n) for n in range(items)],
        )
        (directory / "register.yaml").write_text(_dump(reg.model_dump(mode="json")))
    return sid


def _errors(report: object) -> str:
    return "\n".join(report.errors)  # type: ignore[attr-defined]


# --- intact projects ------------------------------------------------------------------


async def test_intact_project_passes(tmp_path: Path) -> None:
    store, _sid = await _seeded(tmp_path)
    report = await check_integrity(store)
    assert report.ok, report.errors
    assert report.warnings == []
    assert report.head is not None and report.head.event == "risk_item.created"
    assert len(report.entries) == 5


async def test_require_intact_raises_with_every_finding(tmp_path: Path) -> None:
    store, sid = await _seeded(tmp_path)
    assert (await require_intact(store)).ok
    path = _system_dir(tmp_path, sid) / "register.yaml"
    path.write_text(path.read_text().replace("title: r0", "title: edited"))
    (_root(tmp_path) / "audit.head.json").write_text("{}")
    with pytest.raises(IntegrityError) as caught:
        await require_intact(store)
    assert len(caught.value.report.errors) == 2


def test_latest_fingerprints_keeps_the_last_one_per_system() -> None:
    def entry(sid: str, fingerprint: str | None) -> AuditEntry:
        return AuditEntry(
            seq=0, event="e", actor=ACTOR, system_id=sid, register_fingerprint=fingerprint
        )

    entries = [entry("a", "1"), entry("b", "2"), entry("a", "3"), entry("a", None)]
    assert latest_fingerprints(entries) == {"a": "3", "b": "2"}


# --- row 1: the chain -----------------------------------------------------------------


async def test_edited_entry_fails(tmp_path: Path) -> None:
    store, _sid = await _seeded(tmp_path)
    entries = _entries(tmp_path)
    entries[1].actor.identity = "someone-else"
    _write_entries(tmp_path, entries)
    report = await check_integrity(store)
    assert "entry_hash mismatch" in _errors(report)


async def test_garbled_line_fails_without_raising(tmp_path: Path) -> None:
    store, _sid = await _seeded(tmp_path)
    with _log(tmp_path).open("a") as fh:
        fh.write("{not json\n")
    report = await check_integrity(store)
    assert "not valid JSON" in _errors(report)


async def test_log_line_that_is_not_utf8_fails_without_raising(tmp_path: Path) -> None:
    store, _sid = await _seeded(tmp_path)
    with _log(tmp_path).open("ab") as fh:
        fh.write(b"\xff\xfe not text\n")
    report = await check_integrity(store)
    assert "not valid JSON" in _errors(report)


# --- rows 2 and 3: the head file ------------------------------------------------------


async def test_log_cut_back_to_an_earlier_entry_fails(tmp_path: Path) -> None:
    store, _sid = await _seeded(tmp_path)
    lines = _log(tmp_path).read_text().splitlines(keepends=True)
    _log(tmp_path).write_text("".join(lines[:-1]))
    report = await check_integrity(store)
    assert "entries were removed from the end" in _errors(report)


async def test_rewritten_log_fails_on_the_head_file(tmp_path: Path) -> None:
    store, _sid = await _seeded(tmp_path)
    entries = _entries(tmp_path)
    entries[0].actor.identity = "someone-else"
    _write_entries(tmp_path, _relink(entries))
    report = await check_integrity(store)
    assert "the log was rewritten" in _errors(report)


async def test_entries_appended_without_riskforge_fail(tmp_path: Path) -> None:
    store, sid = await _seeded(tmp_path)
    last = _entries(tmp_path)[-1]
    extra = AuditEntry(
        seq=last.seq + 1,
        event="rmf.exported",
        actor=AuditActor(type="human", identity="x"),
        system_id=sid,
        payload={},
        prev_hash=last.entry_hash,
        register_fingerprint=last.register_fingerprint,
    )
    extra.entry_hash = compute_entry_hash(extra)
    with _log(tmp_path).open("a") as fh:
        fh.write(json.dumps(entry_to_dict(extra), separators=(",", ":")) + "\n")
    report = await check_integrity(store)
    assert "RiskForge did not record" in _errors(report)


async def test_unparseable_head_file_fails(tmp_path: Path) -> None:
    store, _sid = await _seeded(tmp_path)
    (_root(tmp_path) / "audit.head.json").write_text("not json")
    report = await check_integrity(store)
    assert "audit.head.json does not parse" in _errors(report)


async def test_deleted_head_file_fails_when_entries_carry_fingerprints(tmp_path: Path) -> None:
    store, _sid = await _seeded(tmp_path)
    lines = _log(tmp_path).read_text().splitlines(keepends=True)
    _log(tmp_path).write_text("".join(lines[:-1]))
    (_root(tmp_path) / "audit.head.json").unlink()
    report = await check_integrity(store)
    assert "audit.head.json is missing" in _errors(report)


async def test_deleted_head_file_fails_when_the_log_holds_events_only_2_0_writes(
    tmp_path: Path,
) -> None:
    # Cut back to the system.created entry, which carries no fingerprint.
    store, _sid = await _seeded(tmp_path)
    lines = _log(tmp_path).read_text().splitlines(keepends=True)
    _log(tmp_path).write_text(lines[0])
    (_root(tmp_path) / "audit.head.json").unlink()
    report = await check_integrity(store)
    assert "audit.head.json is missing" in _errors(report)


# --- rows 4 and 5: register fingerprints ----------------------------------------------


async def test_register_edited_outside_riskforge_fails(tmp_path: Path) -> None:
    store, sid = await _seeded(tmp_path)
    path = _system_dir(tmp_path, sid) / "register.yaml"
    register = yaml.safe_load(path.read_text())
    register["items"][0]["likelihood"] = 1
    path.write_text(_dump(register))
    report = await check_integrity(store)
    assert f"System {sid}: register.yaml was changed outside RiskForge" in _errors(report)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("title: r0", "title: 2026-10-12"),
        ("title: r0", "title: !!binary aGVsbG8="),
        ("title: r0", "title: !!set {a, b}"),
        ("title: r0", "title: r0\n  1: mixed key types"),
        ("title: r0", "title: [unclosed"),
        ("title: r0", "title: 'line\x85break'"),
    ],
    ids=["unquoted-date", "binary", "set", "mixed-keys", "does-not-parse", "u0085"],
)
async def test_register_hand_edits_that_cannot_be_fingerprinted_fail_without_raising(
    tmp_path: Path, old: str, new: str
) -> None:
    store, sid = await _seeded(tmp_path)
    path = _system_dir(tmp_path, sid) / "register.yaml"
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new, 1))
    report = await check_integrity(store)
    assert f"System {sid}: register.yaml was changed outside RiskForge" in _errors(report)


async def test_register_with_no_fingerprint_fails_once_a_head_file_exists(tmp_path: Path) -> None:
    store, _sid = await _seeded(tmp_path)
    audit = AuditEngine(store, ACTOR)
    other = AISystem(name="T", version="1", purpose="hiring", provider_name="P")
    await SystemEngine(store, audit).create(other)
    src = _system_dir(tmp_path, _sid) / "register.yaml"
    shutil.copyfile(src, _system_dir(tmp_path, str(other.id)) / "register.yaml")
    report = await check_integrity(store)
    assert f"System {other.id}: register.yaml has no fingerprint in the audit log" in _errors(
        report
    )


# --- row 6: deleted registers ---------------------------------------------------------


async def test_deleted_register_fails(tmp_path: Path) -> None:
    store, sid = await _seeded(tmp_path)
    (_system_dir(tmp_path, sid) / "register.yaml").unlink()
    report = await check_integrity(store)
    assert f"System {sid}: register.yaml is missing" in _errors(report)


async def test_deleted_register_last_written_by_v113_fails(
    v113_project: tuple[Path, str],
) -> None:
    root, sid = v113_project
    (_system_dir(root, sid) / "register.yaml").unlink()
    report = await check_integrity(FileStore(root))
    assert f"System {sid}: register.yaml is missing" in _errors(report)


async def test_system_with_no_register_and_no_register_events_passes(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    await store.init_project("p", {})
    system = AISystem(name="S", version="1", purpose="p", provider_name="P")
    await SystemEngine(store, AuditEngine(store, ACTOR)).create(system)
    report = await check_integrity(store)
    assert report.ok and report.warnings == []


# --- row 7: missing or empty log ------------------------------------------------------


async def test_missing_log_with_systems_fails(tmp_path: Path) -> None:
    store, _sid = await _seeded(tmp_path)
    _log(tmp_path).unlink()
    (_root(tmp_path) / "audit.head.json").unlink()
    report = await check_integrity(store)
    assert "The audit log is missing or empty" in _errors(report)


async def test_emptied_log_fails(tmp_path: Path) -> None:
    store, _sid = await _seeded(tmp_path)
    _log(tmp_path).write_text("")
    report = await check_integrity(store)
    assert "the audit log is missing or empty" in _errors(report).lower()


async def test_v113_project_without_entries_and_empty_registers_passes_with_a_warning(
    tmp_path: Path,
) -> None:
    (tmp_path / "riskforge.yaml").write_text("project_id: p\n")
    _v113_system_files(tmp_path, items=0)
    _v113_system_files(tmp_path, items=0, register=False)
    report = await check_integrity(FileStore(tmp_path))
    assert report.ok, report.errors
    assert any("holds no entries" in warning for warning in report.warnings)


async def test_v113_project_without_entries_but_with_risks_fails_naming_the_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "riskforge.yaml").write_text("project_id: p\n")
    sid = _v113_system_files(tmp_path, items=2)
    report = await check_integrity(FileStore(tmp_path))
    assert "The audit log is missing or empty" in _errors(report)
    assert f"systems/{sid}/register.yaml" in _errors(report)


# --- rows 8 and 9: system directories -------------------------------------------------


async def test_deleted_system_files_fail(tmp_path: Path) -> None:
    store, sid = await _seeded(tmp_path)
    shutil.rmtree(_system_dir(tmp_path, sid))
    report = await check_integrity(store)
    assert f"System {sid} appears in the audit log, but its files are missing" in _errors(report)


async def test_system_added_by_hand_fails_once_a_head_file_exists(tmp_path: Path) -> None:
    store, _sid = await _seeded(tmp_path)
    added = _v113_system_files(tmp_path, items=0, register=False)
    report = await check_integrity(store)
    assert f"System {added}: no audit entry names it" in _errors(report)


# --- row 10: system.yaml --------------------------------------------------------------


def _edit_system_yaml(project: Path, sid: str, how: str) -> None:
    path = _system_dir(project, sid) / "system.yaml"
    document = yaml.safe_load(path.read_text())
    if how == "does-not-parse":
        path.write_text("name: [unclosed\n")
        return
    if how == "invalid":
        del document["provider_name"]
    elif how == "wrong-id":
        document["id"] = "00000000-0000-4000-8000-000000000000"
    elif how == "differs-from-register":
        document["name"] = "Renamed by hand"
    path.write_text(_dump(document))


@pytest.mark.parametrize(
    ("how", "message"),
    [
        ("does-not-parse", "system.yaml does not parse"),
        ("invalid", "system.yaml is not a valid system record"),
        ("wrong-id", "system.yaml holds id 00000000-0000-4000-8000-000000000000"),
        (
            "differs-from-register",
            "system.yaml differs from the copy in register.yaml: name is 'Renamed by hand' "
            "in system.yaml and 'S' in register.yaml",
        ),
    ],
)
async def test_corrupt_or_edited_system_yaml_fails(tmp_path: Path, how: str, message: str) -> None:
    store, sid = await _seeded(tmp_path)
    _edit_system_yaml(tmp_path, sid, how)
    report = await check_integrity(store)
    assert f"System {sid}: {message}" in _errors(report)


# --- 1.1.3 compatibility and the baseline ---------------------------------------------


async def test_v113_project_passes_with_a_warning(v113_project: tuple[Path, str]) -> None:
    root, sid = v113_project
    report = await check_integrity(FileStore(root))
    assert report.ok, report.errors
    assert report.warnings == [
        f"System {sid}: register.yaml is not covered by a fingerprint yet (last written before "
        "RiskForge 2.0). The next change records one."
    ]


async def test_v113_project_is_covered_after_one_change(v113_project: tuple[Path, str]) -> None:
    root, sid = v113_project
    store = FileStore(root)
    register = await store.read_register(sid)
    target = next(item for item in register.items if not item.accepted)
    engine = RiskEngine(store, AuditEngine(store, ACTOR))
    await engine.accept_risk(sid, str(target.id), "Reviewed after upgrade.", "t")
    report = await check_integrity(store)
    assert report.ok and report.warnings == [], (report.errors, report.warnings)
    assert (root / ".riskforge" / "audit.head.json").exists()
    assert [entry.event for entry in report.entries[-1:]] == ["risk.accepted"]


async def test_first_change_baselines_every_other_system(v113_project: tuple[Path, str]) -> None:
    root, sid = v113_project
    with_register = _v113_system_files(root, items=0)
    without_register = _v113_system_files(root, items=0, register=False)
    store = FileStore(root)
    before = await check_integrity(store)
    assert before.ok, before.errors
    expected = document_fingerprint(await store.read_register_document(with_register))

    register = await store.read_register(sid)
    target = next(item for item in register.items if not item.accepted)
    engine = RiskEngine(store, AuditEngine(store, ACTOR))
    await engine.accept_risk(sid, str(target.id), "Reviewed after upgrade.", "t")

    report = await check_integrity(store)
    assert report.ok and report.warnings == [], (report.errors, report.warnings)
    tail = report.entries[-3:]
    assert [entry.event for entry in tail] == [
        "risk.accepted",
        "register.baselined",
        "register.baselined",
    ]
    baselined = {entry.system_id: entry for entry in tail[1:]}
    assert baselined[with_register].register_fingerprint == expected
    assert baselined[without_register].register_fingerprint is None
    assert baselined[with_register].payload == {"name": "Other"}

    # Only the first 2.0 change records a baseline.
    await engine.accept_risk(sid, str(target.id), "Reviewed again.", "t")
    assert (await store.read_last_audit_entry()).event == "risk.accepted"


async def test_a_new_project_records_no_baseline(tmp_path: Path) -> None:
    store, _sid = await _seeded(tmp_path)
    assert "register.baselined" not in [entry.event for entry in _entries(tmp_path)]


# --- read-only mode and changes in progress -------------------------------------------


async def test_read_only_store_checks_and_refuses_writes(tmp_path: Path) -> None:
    await _seeded(tmp_path)
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    store = FileStore(tmp_path, read_only=True)
    report = await check_integrity(store)
    assert report.ok, report.errors
    with pytest.raises(PermissionError):
        await store.write_system(
            "x", AISystem(name="S", version="1", purpose="p", provider_name="P")
        )
    with pytest.raises(PermissionError):
        await store.init_project("p", {})
    async with store.unit_of_work():
        pass
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before


async def test_read_only_unit_of_work_refuses_an_unfinished_change(tmp_path: Path) -> None:
    await _seeded(tmp_path)
    (_root(tmp_path) / "txn.json").write_text('{"after_seq": 4, "log_size": 0, "files": []}')
    with pytest.raises(PendingChangeError):
        async with FileStore(tmp_path, read_only=True).unit_of_work():
            pass


async def test_settled_check_gives_up_while_a_change_is_in_progress(tmp_path: Path) -> None:
    await _seeded(tmp_path)
    (_root(tmp_path) / "txn.json").write_text('{"after_seq": 4, "log_size": 0, "files": []}')
    store = FileStore(tmp_path, read_only=True)
    with pytest.raises(ChangeInProgressError, match="in progress or unfinished"):
        await check_integrity_settled(store, pause=0)
    assert (_root(tmp_path) / "txn.json").exists()


class _ChangingStore(FileStore):
    """A store whose head moves during the first two checks, as if a writer ran alongside."""

    def __init__(self, project: Path, moves: int) -> None:
        super().__init__(project, read_only=True)
        self.calls = 0
        self.moves = moves

    async def read_commit_markers(self) -> tuple[bytes | None, bytes | None]:
        journal, head = await super().read_commit_markers()
        self.calls += 1
        if self.calls <= 2 * self.moves:
            head = (head or b"") + str(self.calls).encode()
        return journal, head


async def test_settled_check_repeats_when_the_head_moves(tmp_path: Path) -> None:
    await _seeded(tmp_path)
    store = _ChangingStore(tmp_path, moves=2)
    report = await check_integrity_settled(store, pause=0)
    assert report.ok
    assert store.calls == 6


async def test_settled_check_stops_after_three_repeats(tmp_path: Path) -> None:
    await _seeded(tmp_path)
    store = _ChangingStore(tmp_path, moves=4)
    with pytest.raises(ChangeInProgressError):
        await check_integrity_settled(store, pause=0)
    assert store.calls == 8
