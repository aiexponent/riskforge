"""Each tamper probe (one byte changed in the log, last entries cut off, register edited,
last line corrupted, register deleted, system.yaml corrupt, head file deleted, chain
rewritten, log deleted, system directory deleted) makes verify exit 2, and every command
that changes or exports data refuses a tampered project with exit 2 and changes nothing
(PRD-332, PRD-333)."""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml
from conftest import materialise_v113
from rf_testkit import run_rf
from riskforge.integrity.chain import GENESIS_PREV_HASH, compute_entry_hash, entry_to_dict
from riskforge.models.audit import AuditEntry

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "credit-scoring"
RAG_REPORT = REPO / "tests" / "fixtures" / "upstream" / "rag_benchmarking_benchmark_report.json"
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
COMMANDS = (
    "validate",
    "export",
    "export --force",
    "assess",
    "risk accept",
    "risk mitigate",
    "system classify",
    "import",
    "tests generate",
)


def _riskforge(project: Path) -> Path:
    return project / ".riskforge"


def _register_path(project: Path, sid: str) -> Path:
    return _riskforge(project) / "systems" / sid / "register.yaml"


def _log(project: Path) -> Path:
    return _riskforge(project) / "audit.jsonl"


def _head(project: Path) -> Path:
    return _riskforge(project) / "audit.head.json"


def _rf(project: Path, args: list[str]):  # noqa: ANN202
    return run_rf([*args, "--project-dir", str(project)])


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    """A project taken through init, classify, assess, accept and export, verified intact."""
    project = tmp_path_factory.mktemp("pristine")
    config = yaml.safe_load((EXAMPLE / "config.yaml").read_text(encoding="utf-8"))
    init = _rf(
        project,
        [
            "init",
            "-n",
            config["name"],
            "-s",
            str(config["version"]),
            "-p",
            config["purpose"],
            "--provider",
            config["provider"],
            "-c",
            config["category"],
        ],
    )
    assert init.returncode == 0, init.output
    sid = UUID_RE.search(init.output).group(0)
    for args in (
        ["system", "classify", sid, "--confirm"],
        ["assess", sid, "-a", "Alice Chen", "-r", "AI Governance Lead"]
        + ["--answers", str(EXAMPLE / "answers.yaml")],
    ):
        result = _rf(project, args)
        assert result.returncode == 0, result.output
    register = yaml.safe_load(_register_path(project, sid).read_text(encoding="utf-8"))
    for item in register["items"]:
        if item["residual_risk_score"] > register["risk_appetite_threshold"]:
            accepted = _rf(
                project,
                ["risk", "accept", sid, item["id"][:8], "-r", "Residual within appetite."],
            )
            assert accepted.returncode == 0, accepted.output
    exported = _rf(project, ["export", sid, "-f", "json", "-o", str(project / "rmf.json")])
    assert exported.returncode == 0, exported.output
    assert _rf(project, ["verify"]).returncode == 0
    return project, sid


def _copy(pristine: tuple[Path, str], tmp_path: Path) -> tuple[Path, str]:
    source, sid = pristine
    project = tmp_path / "project"
    shutil.copytree(source, project)
    return project, sid


def _snapshot(project: Path) -> dict[str, bytes | None]:
    """Every file and directory under the project, with each file's bytes."""
    return {
        str(path.relative_to(project)): (path.read_bytes() if path.is_file() else None)
        for path in sorted(project.rglob("*"))
    }


def _command(name: str, project: Path, sid: str, rid: str) -> list[str]:
    return {
        "validate": ["validate", sid],
        "export": ["export", sid, "-f", "json", "-o", str(project / "again.json")],
        "export --force": ["export", sid, "-f", "json", "-o", str(project / "forced.json")]
        + ["--force"],
        "assess": ["assess", sid, "-a", "A", "-r", "B", "--answers", str(EXAMPLE / "answers.yaml")],
        "risk accept": ["risk", "accept", sid, rid, "-r", "accepted on a tampered project"],
        "risk mitigate": ["risk", "mitigate", sid, rid]
        + ["-m", "Block release above a 0.10 parity gap", "-c", "preventive", "--owner", "X"],
        "system classify": ["system", "classify", sid, "--confirm"],
        "import": ["import", sid, "-a", "rag-benchmarking", "-r", str(RAG_REPORT)],
        "tests generate": ["tests", "generate", sid],
    }[name]


def _unaccepted_id(project: Path, sid: str) -> str:
    register = yaml.safe_load(_register_path(project, sid).read_text(encoding="utf-8"))
    return next(item["id"] for item in register["items"] if not item["accepted"])[:8]


# ---------------------------------------------------------------- the probes ---- #


def _one_byte_in_line_1(project: Path, sid: str) -> None:
    data = bytearray(_log(project).read_bytes())
    index = data.find(b'"event":"') + len(b'"event":"')
    data[index] = ord("X")
    _log(project).write_bytes(bytes(data))


def _last_entry_cut_off(project: Path, sid: str) -> None:
    lines = _log(project).read_bytes().splitlines(keepends=True)
    _log(project).write_bytes(b"".join(lines[:-1]))


def _register_edited(project: Path, sid: str) -> None:
    path = _register_path(project, sid)
    register = yaml.safe_load(path.read_text(encoding="utf-8"))
    victim = next(item for item in register["items"] if item["risk_score"] == 20)
    victim.update(
        likelihood=1, severity=1, residual_likelihood=1, residual_severity=1, accepted=False
    )
    register["items"].pop(0)
    path.write_text(yaml.dump(register, sort_keys=False), encoding="utf-8")


def _last_line_corrupted(project: Path, sid: str) -> None:
    text = _log(project).read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    assert '"format":"json"' in lines[-1]
    lines[-1] = lines[-1].replace('"format":"json"', '"format":"jsoX"')
    _log(project).write_text("".join(lines), encoding="utf-8")


def _register_deleted(project: Path, sid: str) -> None:
    _register_path(project, sid).unlink()


def _system_yaml_corrupted(project: Path, sid: str) -> None:
    (_riskforge(project) / "systems" / sid / "system.yaml").write_text(
        "name: [unclosed\n", encoding="utf-8"
    )


def _head_file_deleted(project: Path, sid: str) -> None:
    _head(project).unlink()


def _chain_rewritten(project: Path, sid: str) -> None:
    entries = [
        AuditEntry.model_validate(json.loads(line))
        for line in _log(project).read_text(encoding="utf-8").splitlines()
    ]
    entries[0].actor.identity = "someone-else"
    prev = GENESIS_PREV_HASH
    for entry in entries:
        entry.prev_hash = prev
        entry.entry_hash = compute_entry_hash(entry)
        prev = entry.entry_hash
    _log(project).write_text(
        "".join(json.dumps(entry_to_dict(e), separators=(",", ":")) + "\n" for e in entries),
        encoding="utf-8",
    )


def _log_deleted(project: Path, sid: str) -> None:
    _log(project).unlink()


def _log_and_head_deleted(project: Path, sid: str) -> None:
    _log(project).unlink()
    _head(project).unlink()


def _system_directory_deleted(project: Path, sid: str) -> None:
    shutil.rmtree(_riskforge(project) / "systems" / sid)


# The four probes PRD-333 names, then the gaps carried from PRD-331 and PRD-332.
COMMAND_PROBES: dict[str, Callable[[Path, str], None]] = {
    "one byte in line 1": _one_byte_in_line_1,
    "last entry cut off": _last_entry_cut_off,
    "register edited": _register_edited,
    "last line corrupted": _last_line_corrupted,
    "register deleted": _register_deleted,
    "system.yaml corrupted": _system_yaml_corrupted,
    "head file deleted": _head_file_deleted,
}
VERIFY_PROBES: dict[str, Callable[[Path, str], None]] = {
    **COMMAND_PROBES,
    "chain rewritten": _chain_rewritten,
    "log deleted": _log_deleted,
    "log and head file deleted": _log_and_head_deleted,
    "system directory deleted": _system_directory_deleted,
}


def _assert_refused(result, before: dict, project: Path, label: str) -> None:  # noqa: ANN001
    assert result.returncode == 2, f"{label}: exit {result.returncode}\n{result.output}"
    assert "Traceback" not in result.output, label
    assert "Integrity check failed" in result.output, f"{label}: {result.output}"
    assert _snapshot(project) == before, f"{label}: the project changed"


@pytest.mark.parametrize("probe", list(VERIFY_PROBES))
def test_every_probe_fails_verify(pristine, tmp_path: Path, probe: str) -> None:
    project, sid = _copy(pristine, tmp_path)
    VERIFY_PROBES[probe](project, sid)
    result = _rf(project, ["verify"])
    assert result.returncode == 2, result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("probe", list(COMMAND_PROBES))
def test_command_refuses_a_tampered_project(
    pristine, tmp_path: Path, probe: str, command: str
) -> None:
    project, sid = _copy(pristine, tmp_path)
    rid = _unaccepted_id(project, sid)
    COMMAND_PROBES[probe](project, sid)
    before = _snapshot(project)
    result = _rf(project, _command(command, project, sid, rid))
    _assert_refused(result, before, project, f"{command} after {probe}")


def test_every_command_still_works_on_an_intact_project(pristine, tmp_path: Path) -> None:
    project, sid = _copy(pristine, tmp_path)
    rid = _unaccepted_id(project, sid)
    for command in COMMANDS:
        result = _rf(project, _command(command, project, sid, rid))
        assert result.returncode == 0, f"{command}: {result.output}"
        assert "Integrity check failed" not in result.output, command
    assert (project / "again.json").is_file()
    assert (project / "forced.json").is_file()
    assert _rf(project, ["verify"]).returncode == 0


def test_edited_register_is_not_laundered_by_risk_accept(pristine, tmp_path: Path) -> None:
    project, sid = _copy(pristine, tmp_path)
    rid = _unaccepted_id(project, sid)
    _register_edited(project, sid)
    before = _snapshot(project)
    result = _rf(project, _command("risk accept", project, sid, rid))
    _assert_refused(result, before, project, "risk accept after register edit")
    assert "was changed outside RiskForge" in result.output
    assert _rf(project, ["verify"]).returncode == 2


def test_deleted_head_file_does_not_baseline_an_edited_register(pristine, tmp_path: Path) -> None:
    project, sid = _copy(pristine, tmp_path)
    rid = _unaccepted_id(project, sid)
    _register_edited(project, sid)
    _head_file_deleted(project, sid)
    before = _snapshot(project)
    for command in ("risk accept", "system classify", "assess"):
        result = _rf(project, _command(command, project, sid, rid))
        _assert_refused(result, before, project, f"{command} after head deleted")
    assert b"register.baselined" not in _log(project).read_bytes()
    assert _rf(project, ["verify"]).returncode == 2


@pytest.mark.parametrize("command", ["risk accept", "risk mitigate"])
def test_corrupt_last_line_exits_2_in_one_line(pristine, tmp_path: Path, command: str) -> None:
    project, sid = _copy(pristine, tmp_path)
    rid = _unaccepted_id(project, sid)
    _last_line_corrupted(project, sid)
    before = _snapshot(project)
    result = _rf(project, _command(command, project, sid, rid))
    _assert_refused(result, before, project, command)
    assert "entry_hash mismatch" in result.output


@pytest.mark.parametrize("command", ["risk accept", "assess"])
def test_untouched_v113_project_still_accepts_changes(tmp_path: Path, command: str) -> None:
    project, sid = materialise_v113(tmp_path / "v113")
    rid = _unaccepted_id(project, sid)
    assert not _head(project).exists()
    args = _command(command, project, sid, rid)
    if command == "assess":
        # The example answers match the fixture, so re-running them changes nothing
        # (PRD-334); change one answer so assess makes a change.
        answers = yaml.safe_load((EXAMPLE / "answers.yaml").read_text(encoding="utf-8"))
        answers["answers"]["HS-001"] = {"applies": "yes", "likelihood": 2, "severity": 3}
        changed = tmp_path / "answers-changed.yaml"
        changed.write_text(yaml.dump(answers, sort_keys=False), encoding="utf-8")
        args[args.index("--answers") + 1] = str(changed)
    result = _rf(project, args)
    assert result.returncode == 0, result.output
    assert "not covered by a fingerprint yet" in result.output
    assert _head(project).exists()
    verified = _rf(project, ["verify"])
    assert verified.returncode == 0, verified.output
    assert "not covered by a fingerprint yet" not in verified.output


READ_ONLY_COMMANDS = ("validate", "tests generate")


def _set_writable(root: Path, writable: bool) -> None:
    for path in [root, *root.rglob("*")]:
        mode = path.stat().st_mode
        path.chmod(mode | 0o200 if writable else mode & ~0o222)


@pytest.mark.parametrize("command", READ_ONLY_COMMANDS)
def test_read_only_command_works_on_a_read_only_copy(
    pristine, tmp_path: Path, command: str
) -> None:
    project, sid = _copy(pristine, tmp_path)
    rid = _unaccepted_id(project, sid)
    (_riskforge(project) / "audit.lock").unlink(missing_ok=True)
    _set_writable(project, False)
    try:
        before = _snapshot(project)
        result = _rf(project, _command(command, project, sid, rid))
        assert result.returncode == 0, result.output
        assert "Traceback" not in result.output
        assert _snapshot(project) == before
        assert not (_riskforge(project) / "audit.lock").exists()
    finally:
        _set_writable(project, True)


@pytest.mark.parametrize("command", READ_ONLY_COMMANDS)
def test_read_only_command_refuses_a_tampered_read_only_copy(
    pristine, tmp_path: Path, command: str
) -> None:
    project, sid = _copy(pristine, tmp_path)
    rid = _unaccepted_id(project, sid)
    _register_edited(project, sid)
    (_riskforge(project) / "audit.lock").unlink(missing_ok=True)
    _set_writable(project, False)
    try:
        before = _snapshot(project)
        result = _rf(project, _command(command, project, sid, rid))
        _assert_refused(result, before, project, f"{command} on a read-only copy")
    finally:
        _set_writable(project, True)


@pytest.mark.parametrize("command", READ_ONLY_COMMANDS)
def test_read_only_command_waits_out_an_unfinished_change_with_exit_1(
    pristine, tmp_path: Path, command: str
) -> None:
    project, sid = _copy(pristine, tmp_path)
    rid = _unaccepted_id(project, sid)
    last = json.loads(_log(project).read_text(encoding="utf-8").splitlines()[-1])
    journal = _riskforge(project) / "txn.json"
    journal.write_text(
        json.dumps(
            {"after_seq": last["seq"], "log_size": _log(project).stat().st_size, "files": []}
        ),
        encoding="utf-8",
    )
    before = _snapshot(project)
    result = _rf(project, _command(command, project, sid, rid))
    assert result.returncode == 1, result.output
    assert "in progress or unfinished" in result.output
    assert "Traceback" not in result.output
    assert _snapshot(project) == before


# A riskforge process whose integrity check, once it has passed, replaces a stored file
# with an edited copy: the swap a racing writer could make between the check and the
# change's read, made deterministic.
SWAP_AFTER_CHECK = """
import os, shutil, sys
import riskforge.engine.integrity as integrity

edited, target = sys.argv[1], sys.argv[2]
real_check = integrity.check_integrity
swapped = []


async def check_then_swap(storage):
    report = await real_check(storage)
    if not swapped:
        shutil.copyfile(edited, target + ".swap")
        os.replace(target + ".swap", target)
        swapped.append(True)
    return report


integrity.check_integrity = check_then_swap
from riskforge.cli.main import run

sys.argv = ["riskforge", *sys.argv[3:]]
run()
"""


def _run_with_swap(tmp_path: Path, edited: Path, target: Path, args: list[str]):  # noqa: ANN202
    import subprocess
    import sys

    from rf_testkit import offline_env

    script = tmp_path / "swap_after_check.py"
    script.write_text(SWAP_AFTER_CHECK, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(script), str(edited), str(target), *args],
        capture_output=True,
        text=True,
        env=offline_env(),
        stdin=subprocess.DEVNULL,
        timeout=180,
    )
    result.output = result.stdout + result.stderr  # type: ignore[attr-defined]
    return result


@pytest.mark.parametrize(
    "command",
    ["risk accept", "risk mitigate", "system classify", "export", "export --force", "import"]
    + ["assess"],
)
def test_register_swapped_after_the_check_is_refused(
    pristine, tmp_path: Path, command: str
) -> None:
    project, sid = _copy(pristine, tmp_path)
    rid = _unaccepted_id(project, sid)
    target = _register_path(project, sid)
    original = target.read_bytes()
    edited_copy = tmp_path / "edited"
    edited_copy.mkdir()
    shutil.copytree(project, edited_copy / "project")
    _register_edited(edited_copy / "project", sid)
    edited = _register_path(edited_copy / "project", sid)
    log_before = _log(project).read_bytes()
    args = [*_command(command, project, sid, rid), "--project-dir", str(project)]
    result = _run_with_swap(tmp_path, edited, target, args)
    assert target.read_bytes() == edited.read_bytes() != original
    assert result.returncode == 2, result.output
    assert "Traceback" not in result.output
    assert "changed after" in result.output, result.output
    assert _log(project).read_bytes() == log_before
    assert not (project / "again.json").exists()
    assert not (project / "forced.json").exists()
    assert _rf(project, ["verify"]).returncode == 2


def test_system_yaml_swapped_after_the_check_is_refused(pristine, tmp_path: Path) -> None:
    project, sid = _copy(pristine, tmp_path)
    target = _riskforge(project) / "systems" / sid / "system.yaml"
    edited = tmp_path / "system.yaml"
    edited.write_text(
        target.read_text(encoding="utf-8").replace("Acme Financial Services", "Someone Else"),
        encoding="utf-8",
    )
    log_before = _log(project).read_bytes()
    args = ["system", "classify", sid, "--confirm", "--project-dir", str(project)]
    result = _run_with_swap(tmp_path, edited, target, args)
    assert result.returncode == 2, result.output
    assert "system.yaml" in result.output
    assert _log(project).read_bytes() == log_before
    assert _rf(project, ["verify"]).returncode == 2


def test_planted_torn_journal_does_not_cut_the_log(pristine, tmp_path: Path) -> None:
    project, sid = _copy(pristine, tmp_path)
    rid = _unaccepted_id(project, sid)
    lines = _log(project).read_bytes().splitlines(keepends=True)
    # More lines than the log holds after seq 1, so recovery would read them as a torn
    # append and cut them off if it trusted the journal.
    count = len(lines) + 1
    journal = {"after_seq": 1, "log_size": len(b"".join(lines[:2])), "count": count, "files": []}
    (_riskforge(project) / "txn.json").write_text(json.dumps(journal), encoding="utf-8")
    before = _snapshot(project)
    result = _rf(project, _command("risk accept", project, sid, rid))
    assert result.returncode == 2, result.output
    assert "Traceback" not in result.output
    assert "audit.head.json" in result.output
    assert _snapshot(project) == before
    assert _rf(project, ["verify"]).returncode == 2


def test_refusal_after_recovery_does_not_claim_nothing_changed(pristine, tmp_path: Path) -> None:
    project, sid = _copy(pristine, tmp_path)
    rid = _unaccepted_id(project, sid)
    log = _log(project).read_bytes()
    last = json.loads(log.splitlines()[-1])
    journal = {"after_seq": last["seq"], "log_size": len(log), "count": 1, "files": []}
    (_riskforge(project) / "txn.json").write_text(json.dumps(journal), encoding="utf-8")
    _log(project).write_bytes(log + b'{"seq":')
    _register_edited(project, sid)
    result = _rf(project, _command("risk accept", project, sid, rid))
    assert result.returncode == 2, result.output
    assert _log(project).read_bytes() == log
    assert "Nothing was changed" not in result.output
    assert "unfinished earlier change" in result.output


@pytest.mark.parametrize("command", READ_ONLY_COMMANDS)
def test_read_only_command_refuses_a_register_swapped_after_the_check(
    pristine, tmp_path: Path, command: str
) -> None:
    project, sid = _copy(pristine, tmp_path)
    rid = _unaccepted_id(project, sid)
    target = _register_path(project, sid)
    edited_copy = tmp_path / "edited"
    edited_copy.mkdir()
    shutil.copytree(project, edited_copy / "project")
    _register_edited(edited_copy / "project", sid)
    edited = _register_path(edited_copy / "project", sid)
    log_before = _log(project).read_bytes()
    args = [*_command(command, project, sid, rid), "--project-dir", str(project)]
    result = _run_with_swap(tmp_path, edited, target, args)
    assert target.read_bytes() == edited.read_bytes()
    assert result.returncode == 2, result.output
    assert "Traceback" not in result.output
    assert "changed after" in result.output, result.output
    assert "All gates passed" not in result.output
    assert "Derived" not in result.output
    assert _log(project).read_bytes() == log_before
