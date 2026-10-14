"""riskforge verify on intact, tampered, 1.1.3 and read-only projects (PRD-332, ADR-03)."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
import yaml
from rf_testkit import run_rf

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _seed(project: Path) -> str:
    result = run_rf(
        [
            "init",
            "-n",
            "S",
            "-s",
            "1",
            "-p",
            "credit scoring for loans",
            "--provider",
            "P",
            "-c",
            "essential_services",
            "--project-dir",
            str(project),
        ]
    )
    assert result.returncode == 0, result.output
    sid = UUID_RE.search(result.output).group(0)
    answers = project / "answers.yaml"
    answers.write_text(
        "add_patterns: false\nanswers:\n"
        "  PR-001: { applies: yes, likelihood: 3, severity: 4 }\n"
        "  TR-001: { applies: yes, likelihood: 2, severity: 3 }\n"
    )
    assessed = run_rf(
        [
            "assess",
            sid,
            "-a",
            "A",
            "-r",
            "B",
            "--answers",
            str(answers),
            "--project-dir",
            str(project),
        ]
    )
    assert assessed.returncode == 0, assessed.output
    return sid


def _verify(project: Path):  # noqa: ANN202
    return run_rf(["verify", "--project-dir", str(project)])


def _assert_one_line_findings(output: str) -> None:
    assert "Traceback" not in output
    assert "—" not in output


def _set_writable(root: Path, writable: bool) -> None:
    for path in [root, *root.rglob("*")]:
        mode = path.stat().st_mode
        path.chmod(mode | 0o200 if writable else mode & ~0o222)


def _listing(root: Path) -> list[tuple[str, int]]:
    return sorted((str(p.relative_to(root)), p.stat().st_mtime_ns) for p in root.rglob("*"))


def _log(project: Path) -> Path:
    return project / ".riskforge" / "audit.jsonl"


def test_intact_project_verifies_and_writes_nothing(tmp_path: Path) -> None:
    _seed(tmp_path)
    before = _listing(tmp_path)
    result = _verify(tmp_path)
    assert result.returncode == 0, result.output
    assert "Audit chain verified: no tampering detected." in result.output
    assert _listing(tmp_path) == before


def test_hand_edited_register_fails_verify(tmp_path: Path) -> None:
    sid = _seed(tmp_path)
    path = tmp_path / ".riskforge" / "systems" / sid / "register.yaml"
    register = yaml.safe_load(path.read_text())
    register["items"][0]["severity"] = 1
    path.write_text(yaml.dump(register, sort_keys=False))
    result = _verify(tmp_path)
    assert result.returncode == 2, result.output
    assert "changed outside RiskForge" in result.output
    _assert_one_line_findings(result.output)


@pytest.mark.parametrize(
    "edit",
    ["title: 2026-10-12", "title: !!binary aGVsbG8=", "title: !!set {a, b}", "title: [x"],
    ids=["unquoted-date", "binary", "set", "does-not-parse"],
)
def test_register_edits_that_cannot_be_fingerprinted_exit_2_without_a_traceback(
    tmp_path: Path, edit: str
) -> None:
    sid = _seed(tmp_path)
    path = tmp_path / ".riskforge" / "systems" / sid / "register.yaml"
    text = path.read_text()
    title_line = next(line for line in text.splitlines() if line.strip().startswith("title:"))
    path.write_text(text.replace(title_line.strip(), edit, 1))
    result = _verify(tmp_path)
    assert result.returncode == 2, result.output
    assert "changed outside RiskForge" in result.output
    _assert_one_line_findings(result.output)


def test_deleted_log_fails_verify(tmp_path: Path) -> None:
    _seed(tmp_path)
    _log(tmp_path).unlink()
    (tmp_path / ".riskforge" / "audit.head.json").unlink()
    result = _verify(tmp_path)
    assert result.returncode == 2, result.output
    assert "The audit log is missing or empty" in result.output


def test_log_with_its_last_entries_removed_fails_verify(tmp_path: Path) -> None:
    _seed(tmp_path)
    lines = _log(tmp_path).read_text().splitlines(keepends=True)
    _log(tmp_path).write_text("".join(lines[:-2]))
    result = _verify(tmp_path)
    assert result.returncode == 2, result.output
    assert "entries were removed from the end" in result.output


def test_rewritten_log_fails_verify(tmp_path: Path) -> None:
    from riskforge.integrity.chain import GENESIS_PREV_HASH, compute_entry_hash, entry_to_dict
    from riskforge.models.audit import AuditEntry

    _seed(tmp_path)
    entries = [
        AuditEntry.model_validate(json.loads(x)) for x in _log(tmp_path).read_text().splitlines()
    ]
    entries[0].actor.identity = "someone-else"
    prev = GENESIS_PREV_HASH
    for entry in entries:
        entry.prev_hash = prev
        entry.entry_hash = compute_entry_hash(entry)
        prev = entry.entry_hash
    _log(tmp_path).write_text(
        "".join(json.dumps(entry_to_dict(e), separators=(",", ":")) + "\n" for e in entries)
    )
    result = _verify(tmp_path)
    assert result.returncode == 2, result.output
    assert "the log was rewritten" in result.output


def test_deleted_system_files_fail_verify(tmp_path: Path) -> None:
    sid = _seed(tmp_path)
    shutil.rmtree(tmp_path / ".riskforge" / "systems" / sid)
    result = _verify(tmp_path)
    assert result.returncode == 2, result.output
    assert "its files are missing" in result.output


def test_every_finding_is_reported_on_its_own_line(tmp_path: Path) -> None:
    sid = _seed(tmp_path)
    path = tmp_path / ".riskforge" / "systems" / sid / "system.yaml"
    path.write_text(path.read_text().replace("name: S", "name: Renamed", 1))
    register = tmp_path / ".riskforge" / "systems" / sid / "register.yaml"
    register.write_text(register.read_text().replace("assessor_name: A", "assessor_name: Z", 1))
    result = _verify(tmp_path)
    assert result.returncode == 2, result.output
    findings = [line for line in result.output.splitlines() if line.strip().startswith("•")]
    assert len(findings) == 2, result.output
    _assert_one_line_findings(result.output)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("name: S", "name: [unclosed", "system.yaml does not parse"),
        ("provider_name: P", "provider_nam: P", "system.yaml is not a valid system record"),
        ("id: ", "id: 00000000-0000-4000-8000-000000000000\nold_id: ", "system.yaml holds id"),
        ("name: S", "name: Renamed", "system.yaml differs from the copy in register.yaml"),
    ],
    ids=["does-not-parse", "invalid", "wrong-id", "differs-from-register"],
)
def test_corrupt_system_yaml_fails_verify(tmp_path: Path, old: str, new: str, message: str) -> None:
    sid = _seed(tmp_path)
    path = tmp_path / ".riskforge" / "systems" / sid / "system.yaml"
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new, 1))
    result = _verify(tmp_path)
    assert result.returncode == 2, result.output
    assert message in result.output
    _assert_one_line_findings(result.output)


def test_v113_fixture_verifies_with_a_warning(v113_project: tuple[Path, str]) -> None:
    root, _sid = v113_project
    result = _verify(root)
    assert result.returncode == 0, result.output
    assert "not covered by a fingerprint" in result.output
    assert not (root / ".riskforge" / "audit.head.json").exists()


def test_v113_fixture_with_its_register_deleted_fails_verify(
    v113_project: tuple[Path, str],
) -> None:
    root, sid = v113_project
    (root / ".riskforge" / "systems" / sid / "register.yaml").unlink()
    result = _verify(root)
    assert result.returncode == 2, result.output
    assert "register.yaml is missing" in result.output


def test_read_only_copy_verifies_without_writing(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _seed(project)
    archive = tmp_path / "archive"
    shutil.copytree(project, archive)
    (archive / ".riskforge" / "audit.lock").unlink(missing_ok=True)
    _set_writable(archive, False)
    try:
        before = _listing(archive)
        result = _verify(archive)
        assert result.returncode == 0, result.output
        assert _listing(archive) == before
        assert not (archive / ".riskforge" / "audit.lock").exists()
    finally:
        _set_writable(archive, True)


def test_read_only_copy_still_detects_tampering(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sid = _seed(project)
    path = project / ".riskforge" / "systems" / sid / "register.yaml"
    path.write_text(path.read_text().replace("likelihood: 3", "likelihood: 1", 1))
    _set_writable(project, False)
    try:
        before = _listing(project)
        result = _verify(project)
        assert result.returncode == 2, result.output
        assert _listing(project) == before
    finally:
        _set_writable(project, True)


def test_verify_while_a_change_is_unfinished_exits_1(tmp_path: Path) -> None:
    _seed(tmp_path)
    journal = tmp_path / ".riskforge" / "txn.json"
    journal.write_text('{"after_seq": 3, "log_size": 0, "files": []}')
    result = _verify(tmp_path)
    assert result.returncode == 1, result.output
    assert "in progress or unfinished" in result.output
    assert journal.exists()
    errors = [line for line in result.output.splitlines() if line.strip()]
    assert len(errors) == 1, result.output
    _assert_one_line_findings(result.output)


def test_verify_help_names_exit_1_for_a_change_in_progress() -> None:
    result = run_rf(["verify", "--help"])
    assert result.returncode == 0
    assert "change is in progress" in result.output
