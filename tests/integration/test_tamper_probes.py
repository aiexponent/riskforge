"""Every tamper probe of the 2026-10-10 audit makes verify exit 2, and every command that
changes or exports data refuses a tampered project with exit 2 and changes nothing
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
    result = _rf(project, _command(command, project, sid, rid))
    assert result.returncode == 0, result.output
    assert "not covered by a fingerprint yet" in result.output
    assert _head(project).exists()
    verified = _rf(project, ["verify"])
    assert verified.returncode == 0, verified.output
    assert "not covered by a fingerprint yet" not in verified.output
