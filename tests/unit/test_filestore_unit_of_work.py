"""FileStore unit of work: a change and its audit entry land together or not at all (PRD-331)."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import riskforge.storage.filesystem as filesystem
from filelock import FileLock, Timeout
from riskforge.engine.audit import AuditEngine
from riskforge.models.audit import AuditActor
from riskforge.models.register import RiskRegister
from riskforge.models.risk import Likelihood, Mitigation, RiskDimension, RiskItem, Severity
from riskforge.models.system import AISystem
from riskforge.storage.errors import (
    AuditLogCorruptError,
    ProjectLockedError,
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
    async with audit.unit_of_work():
        await store.write_system(str(system.id), system)
        await audit.record("system.created", str(system.id), {})
    return store, audit, system


def _journal(root: Path, after_seq: int, files: list[str]) -> None:
    """Write the journal a commit leaves behind when the process stops before finishing."""
    log_size = (root / "audit.jsonl").stat().st_size
    (root / "txn.json").write_text(
        json.dumps({"after_seq": after_seq, "log_size": log_size, "files": files})
    )


async def _next_entry_line(store: FileStore, sid: str) -> bytes:
    """The bytes the next audit entry would append, built the way AuditEngine builds it."""
    from riskforge.integrity.chain import compute_entry_hash, entry_to_dict
    from riskforge.models.audit import AuditEntry

    last = await store.read_last_audit_entry()
    entry = AuditEntry(
        seq=last.seq + 1,
        event="register.created",
        timestamp=datetime.now(UTC),
        actor=AuditActor(type="human", identity="t"),
        system_id=sid,
        payload={},
        prev_hash=last.entry_hash,
        entry_hash="",
    )
    entry.entry_hash = compute_entry_hash(entry)
    return (json.dumps(entry_to_dict(entry), separators=(",", ":")) + "\n").encode()


async def test_change_and_entry_commit_together(tmp_path: Path) -> None:
    store, audit, system = await _project(tmp_path)
    sid = str(system.id)
    async with audit.unit_of_work():
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
    assert not (tmp_path / ".riskforge" / "systems" / str(system.id)).exists()


async def test_reads_inside_a_unit_of_work_see_its_own_writes(tmp_path: Path) -> None:
    store, audit, system = await _project(tmp_path)
    sid = str(system.id)
    async with audit.unit_of_work():
        await store.write_register(sid, _register(system))
        assert (await store.read_register(sid)).assessor_name == "A"
        await audit.record("register.created", sid, {})


async def test_nested_unit_of_work_joins_the_outer_one(tmp_path: Path) -> None:
    store, audit, system = await _project(tmp_path)
    sid = str(system.id)
    async with audit.unit_of_work():
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
        async with audit.unit_of_work():
            await store.write_register(sid, _register(system))
            await audit.record("register.created", sid, {})
    monkeypatch.setattr(filesystem.os, "replace", real_replace)
    assert (tmp_path / ".riskforge" / "txn.json").exists()
    async with store.unit_of_work():
        # Recovery runs before the scope's own work starts.
        assert not (tmp_path / ".riskforge" / "txn.json").exists()
        assert (await store.read_register(sid)).system.id == system.id
    assert (await store.read_register(sid)).system.id == system.id
    entries = [entry async for entry in store.read_audit()]
    assert entries[-1].event == "register.created"
    head = json.loads((tmp_path / ".riskforge" / "audit.head.json").read_text())
    assert head == {"seq": entries[-1].seq, "entry_hash": entries[-1].entry_hash}


async def test_journal_is_written_first_and_removed_last(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, audit, system = await _project(tmp_path)
    sid = str(system.id)
    root = tmp_path / ".riskforge"
    log_lines_before = len((root / "audit.jsonl").read_text().splitlines())
    real_replace = os.replace
    steps: list[tuple[str, bool, int]] = []

    def record_replace(src, dst):
        result = real_replace(src, dst)
        name = Path(dst).name
        if not name.endswith(".pending"):
            log_lines = len((root / "audit.jsonl").read_text().splitlines())
            steps.append((name, (root / "txn.json").exists(), log_lines))
        return result

    monkeypatch.setattr(filesystem.os, "replace", record_replace)
    async with audit.unit_of_work():
        await store.write_register(sid, _register(system))
        assert steps == []  # staged writes touch only .pending files
        await audit.record("register.created", sid, {})
    monkeypatch.setattr(filesystem.os, "replace", real_replace)

    # The journal lands before the append and before anything is renamed into place.
    assert steps[0] == ("txn.json", True, log_lines_before)
    assert {name for name, _, _ in steps[1:]} == {
        "register.yaml",
        "mitigations.yaml",
        "audit.head.json",
    }
    # Every later step runs after the append and while the journal still exists.
    assert all(journal and lines == log_lines_before + 1 for _, journal, lines in steps[1:])
    assert steps[-1][0] == "audit.head.json"
    assert not (root / "txn.json").exists()


async def test_recovery_runs_under_the_project_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _audit, _system = await _project(tmp_path)
    lock_path = tmp_path / ".riskforge" / "audit.lock"
    real_recover = store._recover
    held: list[bool] = []

    def checked_recover() -> None:
        other = FileLock(str(lock_path))
        try:
            other.acquire(timeout=0)
        except Timeout:
            held.append(True)
        else:
            other.release()
            held.append(False)
        real_recover()

    monkeypatch.setattr(store, "_recover", checked_recover)
    async with store.unit_of_work():
        assert held == [True]
    assert held == [True, True]


async def test_change_staged_before_a_crash_is_rolled_back(tmp_path: Path) -> None:
    store, _audit, system = await _project(tmp_path)
    sid = str(system.id)
    root = tmp_path / ".riskforge"
    last = await store.read_last_audit_entry()
    pending = root / "systems" / sid / "register.yaml.pending"
    pending.write_text("garbage: true\n")
    _journal(root, last.seq, [f"systems/{sid}/register.yaml"])
    head_before = (root / "audit.head.json").read_text()
    async with store.unit_of_work():
        assert not pending.exists()
        assert not (root / "txn.json").exists()
    with pytest.raises(RegisterNotFoundError):
        await store.read_register(sid)
    assert (root / "audit.head.json").read_text() == head_before


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
    async with audit.unit_of_work():
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


async def _assert_rolled_back_and_usable(
    store: FileStore, audit: AuditEngine, system: AISystem, log_before: bytes
) -> None:
    root = store._root
    sid = str(system.id)
    async with store.unit_of_work():
        assert (root / "audit.jsonl").read_bytes() == log_before
        assert not (root / "txn.json").exists()
        assert not list(root.rglob("*.pending"))
    with pytest.raises(RegisterNotFoundError):
        await store.read_register(sid)
    async with audit.unit_of_work():
        await store.write_register(sid, _register(system))
        await audit.record("register.created", sid, {})
    assert (await store.read_register(sid)).system.id == system.id
    ok, errors = await store.verify_chain()
    assert ok, errors


@pytest.mark.parametrize("keep", ["half", "all_but_newline"])
async def test_torn_audit_line_from_a_stopped_process_is_rolled_back(
    tmp_path: Path, keep: str
) -> None:
    store, audit, system = await _project(tmp_path)
    sid = str(system.id)
    root = tmp_path / ".riskforge"
    log_before = (root / "audit.jsonl").read_bytes()
    last = await store.read_last_audit_entry()
    (root / "systems" / sid / "register.yaml.pending").write_text("garbage: true\n")
    _journal(root, last.seq, [f"systems/{sid}/register.yaml"])
    line = await _next_entry_line(store, sid)
    torn = line[: len(line) // 2] if keep == "half" else line[:-1]
    with (root / "audit.jsonl").open("ab") as fh:
        fh.write(torn)
    await _assert_rolled_back_and_usable(store, audit, system, log_before)


async def test_audit_append_that_fails_part_way_is_rolled_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, audit, system = await _project(tmp_path)
    sid = str(system.id)
    log_before = (tmp_path / ".riskforge" / "audit.jsonl").read_bytes()
    real_write = os.write

    def disk_fills_up(fd: int, data: bytes) -> int:
        if data.endswith(b"\n") and b'"register.created"' in data:
            real_write(fd, data[: len(data) // 2])
            raise OSError(28, "No space left on device")
        return real_write(fd, data)

    monkeypatch.setattr(filesystem.os, "write", disk_fills_up)
    with pytest.raises(OSError, match="No space left"):
        async with audit.unit_of_work():
            await store.write_register(sid, _register(system))
            await audit.record("register.created", sid, {})
    monkeypatch.setattr(filesystem.os, "write", real_write)
    await _assert_rolled_back_and_usable(store, audit, system, log_before)


async def test_entries_beyond_an_interrupted_commit_are_never_truncated(tmp_path: Path) -> None:
    store, _audit, system = await _project(tmp_path)
    sid = str(system.id)
    root = tmp_path / ".riskforge"
    last = await store.read_last_audit_entry()
    _journal(root, last.seq, [])
    line = await _next_entry_line(store, sid)
    with (root / "audit.jsonl").open("ab") as fh:
        fh.write(line + line)
    log_after = (root / "audit.jsonl").read_bytes()
    with pytest.raises(AuditLogCorruptError, match="left as it is"):
        async with store.unit_of_work():
            pass
    assert (root / "audit.jsonl").read_bytes() == log_after
    assert (root / "txn.json").exists()


async def test_a_failing_recovery_does_not_hide_the_original_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _audit, _system = await _project(tmp_path)
    real_recover = store._recover
    calls = 0

    def recover_fails_on_exit() -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("recovery could not finish")
        real_recover()

    monkeypatch.setattr(store, "_recover", recover_fails_on_exit)
    with pytest.raises(ValueError, match="the original problem") as caught:
        async with store.unit_of_work():
            raise ValueError("the original problem")
    assert any("recovery could not finish" in note for note in caught.value.__notes__)


async def test_first_append_makes_the_new_audit_log_durable_before_renames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FileStore(tmp_path)
    await store.init_project("p", {})
    root = tmp_path / ".riskforge"
    events: list[tuple[str, str, bool]] = []
    real_fsync_dir = filesystem._fsync_dir
    real_replace = os.replace

    def logged_fsync_dir(directory: Path) -> None:
        events.append(("fsync", Path(directory).name, (root / "audit.jsonl").exists()))
        real_fsync_dir(directory)

    def logged_replace(src, dst):
        events.append(("replace", Path(dst).name, (root / "audit.jsonl").exists()))
        return real_replace(src, dst)

    monkeypatch.setattr(filesystem, "_fsync_dir", logged_fsync_dir)
    monkeypatch.setattr(filesystem.os, "replace", logged_replace)
    system = AISystem(name="S", version="1", purpose="p", provider_name="P")
    audit = AuditEngine(store, AuditActor(type="human", identity="t"))
    async with audit.unit_of_work():
        await store.write_system(str(system.id), system)
        await audit.record("system.created", str(system.id), {})
    rename = events.index(("replace", "system.yaml", True))
    assert ("fsync", ".riskforge", True) in events[:rename]


async def test_crash_journal_for_a_new_system_leaves_no_empty_directory(tmp_path: Path) -> None:
    store, _audit, _system = await _project(tmp_path)
    root = tmp_path / ".riskforge"
    last = await store.read_last_audit_entry()
    new_dir = root / "systems" / "11111111-2222-3333-4444-555555555555"
    new_dir.mkdir()
    (new_dir / "system.yaml.pending").write_text("name: half made\n")
    _journal(root, last.seq, [f"systems/{new_dir.name}/system.yaml"])
    async with store.unit_of_work():
        pass
    assert not new_dir.exists()
    assert (root / "systems" / str(_system.id)).is_dir()


async def test_a_clean_exit_with_unrecorded_writes_is_an_error(tmp_path: Path) -> None:
    store, _audit, system = await _project(tmp_path)
    sid = str(system.id)
    with pytest.raises(RuntimeError, match="no audit entry"):
        async with store.unit_of_work():
            await store.write_register(sid, _register(system))
    with pytest.raises(RegisterNotFoundError):
        await store.read_register(sid)
    assert not list(tmp_path.rglob("*.pending"))


async def test_two_stores_for_one_project_share_a_nested_unit_of_work(tmp_path: Path) -> None:
    store, audit, system = await _project(tmp_path)
    sid = str(system.id)
    (tmp_path / "sub").mkdir()
    other = FileStore(tmp_path / "sub" / "..")

    async def nested() -> None:
        async with audit.unit_of_work():
            async with other.unit_of_work():
                await other.write_register(sid, _register(system))
            assert (await store.read_register(sid)).assessor_name == "A"
            await audit.record("register.created", sid, {})

    await asyncio.wait_for(nested(), timeout=10)
    assert (await other.read_register(sid)).system.id == system.id
    assert not list(tmp_path.rglob("*.pending"))


async def test_waiting_for_a_held_lock_gives_up_with_a_clear_error(tmp_path: Path) -> None:
    await _project(tmp_path)
    impatient = FileStore(tmp_path, lock_timeout=0.3)
    holder = FileLock(str(tmp_path / ".riskforge" / "audit.lock"))
    holder.acquire()
    try:
        with pytest.raises(ProjectLockedError, match="Another riskforge process") as caught:
            async with impatient.unit_of_work():
                pass
    finally:
        holder.release()
    assert "\n" not in str(caught.value)
    async with impatient.unit_of_work():
        pass


async def test_read_last_audit_entry_refuses_a_malformed_line(tmp_path: Path) -> None:
    store, _audit, _system = await _project(tmp_path)
    with (tmp_path / ".riskforge" / "audit.jsonl").open("a", encoding="utf-8") as fh:
        fh.write('{"seq": "not a number"}\n')
    with pytest.raises(AuditLogCorruptError):
        await store.read_last_audit_entry()


# --- several entries in one commit (PRD-332, ADR-03 section 4) --------------------------


def _chained(last, sid: str, count: int, fingerprint: str | None = None) -> list:  # noqa: ANN001
    from riskforge.integrity.chain import compute_entry_hash
    from riskforge.models.audit import AuditEntry

    entries = []
    prev, seq = last.entry_hash, last.seq + 1
    for n in range(count):
        entry = AuditEntry(
            seq=seq + n,
            event="register.created" if n == 0 else "register.baselined",
            actor=AuditActor(type="human", identity="t"),
            system_id=sid,
            payload={},
            prev_hash=prev,
            register_fingerprint=fingerprint,
        )
        entry.entry_hash = compute_entry_hash(entry)
        prev = entry.entry_hash
        entries.append(entry)
    return entries


def _line(entry) -> bytes:  # noqa: ANN001
    from riskforge.integrity.chain import entry_to_dict

    return (json.dumps(entry_to_dict(entry), separators=(",", ":")) + "\n").encode()


def _journal_for(root: Path, after_seq: int, count: int, files: list[str]) -> None:
    log_size = (root / "audit.jsonl").stat().st_size
    journal = {"after_seq": after_seq, "log_size": log_size, "count": count, "files": files}
    (root / "txn.json").write_text(json.dumps(journal))


@pytest.mark.parametrize("written", ["none", "one", "two", "two-and-a-half"])
async def test_multi_entry_append_cut_short_is_rolled_back(tmp_path: Path, written: str) -> None:
    from riskforge.engine.integrity import check_integrity

    store, audit, system = await _project(tmp_path)
    sid = str(system.id)
    root = tmp_path / ".riskforge"
    log_before = (root / "audit.jsonl").read_bytes()
    last = await store.read_last_audit_entry()
    (root / "systems" / sid / "register.yaml.pending").write_text("garbage: true\n")
    _journal_for(root, last.seq, 3, [f"systems/{sid}/register.yaml"])
    lines = [_line(entry) for entry in _chained(last, sid, 3)]
    tail = {
        "none": b"",
        "one": lines[0],
        "two": lines[0] + lines[1],
        "two-and-a-half": lines[0] + lines[1] + lines[2][:10],
    }[written]
    with (root / "audit.jsonl").open("ab") as fh:
        fh.write(tail)
    await _assert_rolled_back_and_usable(store, audit, system, log_before)
    report = await check_integrity(store)
    assert report.ok, report.errors


async def test_multi_entry_append_that_reached_the_log_is_rolled_forward(tmp_path: Path) -> None:
    import yaml
    from riskforge.engine.integrity import check_integrity
    from riskforge.integrity.canonical import document_fingerprint

    store, _audit, system = await _project(tmp_path)
    sid = str(system.id)
    root = tmp_path / ".riskforge"
    last = await store.read_last_audit_entry()
    text = yaml.dump(
        _register(system).model_dump(mode="json"), sort_keys=False, allow_unicode=True
    ).encode()
    (root / "systems" / sid / "register.yaml.pending").write_bytes(text)
    entries = _chained(last, sid, 3, document_fingerprint(yaml.safe_load(text)))
    _journal_for(root, last.seq, 3, [f"systems/{sid}/register.yaml"])
    with (root / "audit.jsonl").open("ab") as fh:
        fh.write(b"".join(_line(entry) for entry in entries))
    async with store.unit_of_work():
        assert not (root / "txn.json").exists()
    assert (await store.read_register(sid)).system.id == system.id
    head = json.loads((root / "audit.head.json").read_text())
    assert head == {"seq": entries[-1].seq, "entry_hash": entries[-1].entry_hash}
    report = await check_integrity(store)
    assert report.ok, report.errors


async def test_an_entry_beyond_a_multi_entry_append_is_never_truncated(tmp_path: Path) -> None:
    store, _audit, system = await _project(tmp_path)
    sid = str(system.id)
    root = tmp_path / ".riskforge"
    last = await store.read_last_audit_entry()
    entries = _chained(last, sid, 3)
    _journal_for(root, last.seq, 2, [])
    with (root / "audit.jsonl").open("ab") as fh:
        fh.write(b"".join(_line(entry) for entry in entries))
    log_after = (root / "audit.jsonl").read_bytes()
    with pytest.raises(AuditLogCorruptError, match="left as it is"):
        async with store.unit_of_work():
            pass
    assert (root / "audit.jsonl").read_bytes() == log_after


async def test_append_refuses_entries_that_are_not_chained(tmp_path: Path) -> None:
    store, _audit, system = await _project(tmp_path)
    last = await store.read_last_audit_entry()
    first, _second, third = _chained(last, str(system.id), 3)
    async with store.unit_of_work():
        with pytest.raises(ValueError, match="chained"):
            await store.append_audit([first, third])


@pytest.mark.parametrize(
    "journal",
    [
        "not json",
        '{"after_seq": 0, "log_size": 0}',
        '{"after_seq": 0, "log_size": 0, "files": ["../../outside"]}',
        '{"after_seq": 0, "log_size": 0, "files": ["systems/x/other.txt"]}',
        '{"after_seq": "0", "log_size": 0, "files": []}',
    ],
)
async def test_malformed_journal_stops_recovery_with_a_typed_error(
    tmp_path: Path, journal: str
) -> None:
    from riskforge.storage.errors import StoredFileCorruptError

    store, _audit, _system = await _project(tmp_path)
    root = tmp_path / ".riskforge"
    (root / "txn.json").write_text(journal)
    log_before = (root / "audit.jsonl").read_bytes()
    with pytest.raises(StoredFileCorruptError, match="txn.json"):
        async with store.unit_of_work():
            pass
    assert (root / "audit.jsonl").read_bytes() == log_before
    assert (root / "txn.json").read_text() == journal
