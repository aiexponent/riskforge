"""riskforge verify --strict: warnings about missing fingerprint coverage fail with exit 2."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml
from rf_testkit import run_rf

UNCOVERED = "is not covered by a fingerprint yet"
NO_HEAD = "There is no .riskforge/audit.head.json"


def _verify(project: Path, *extra: str):  # noqa: ANN202
    return run_rf(["verify", "--project-dir", str(project), *extra])


def _accept_one(project: Path, sid: str) -> None:
    register = project / ".riskforge" / "systems" / sid / "register.yaml"
    items = yaml.safe_load(register.read_text(encoding="utf-8"))["items"]
    rid = next(item["id"] for item in items if not item["accepted"])[:8]
    result = run_rf(
        ["risk", "accept", sid, rid, "-r", "Reviewed after the upgrade.", "--by", "Owner"]
        + ["--project-dir", str(project)]
    )
    assert result.returncode == 0, result.output


def test_strict_fails_a_v113_project_listing_each_finding(v113_project: tuple[Path, str]) -> None:
    root, sid = v113_project
    result = _verify(root, "--strict")
    assert result.returncode == 2, result.output
    findings = [line for line in result.stderr.splitlines() if line.strip().startswith("•")]
    assert len(findings) == 2, result.stderr
    assert NO_HEAD in findings[0]
    assert f"System {sid}: register.yaml {UNCOVERED}" in findings[1]
    assert "Integrity check failed with 2 findings:" in result.stderr
    assert result.output.count(UNCOVERED) == 1
    assert "no tampering detected" not in result.output
    assert "—" not in result.output


def test_without_strict_a_v113_project_still_passes_with_the_warning(
    v113_project: tuple[Path, str],
) -> None:
    root, _sid = v113_project
    result = _verify(root)
    assert result.returncode == 0, result.output
    assert UNCOVERED in result.stderr
    assert "no tampering detected" in result.stdout


def test_strict_passes_once_riskforge_2_has_written_the_project(
    v113_project: tuple[Path, str],
) -> None:
    root, sid = v113_project
    _accept_one(root, sid)
    result = _verify(root, "--strict")
    assert result.returncode == 0, result.output
    assert UNCOVERED not in result.output
    assert "no tampering detected" in result.stdout


def test_strict_still_fails_a_tampered_project_with_exit_2(
    v113_project: tuple[Path, str],
) -> None:
    root, sid = v113_project
    _accept_one(root, sid)
    register = root / ".riskforge" / "systems" / sid / "register.yaml"
    register.write_text(register.read_text(encoding="utf-8") + "\n# edited\nextra: 1\n")
    result = _verify(root, "--strict")
    assert result.returncode == 2, result.output
    assert "was changed outside RiskForge" in result.stderr


def test_strict_with_file_is_a_usage_error(v113_project: tuple[Path, str]) -> None:
    root, _sid = v113_project
    result = _verify(root, "--strict", "--file", str(root / "rmf.json"))
    assert result.returncode == 3, result.output
    assert "--strict cannot be combined with --file" in result.stderr
    assert "—" not in result.output


def test_help_mentions_strict() -> None:
    result = run_rf(["verify", "--help"])
    assert result.returncode == 0, result.output
    assert "--strict" in result.stdout
    assert "—" not in result.stdout


def _findings(result) -> list[str]:  # noqa: ANN001
    return [line.strip() for line in result.stderr.splitlines() if line.strip().startswith("•")]


def _init(project: Path) -> None:
    result = run_rf(
        ["init", "-n", "S", "-s", "1", "-p", "credit scoring for loans", "--provider", "P"]
        + ["-c", "essential_services", "--project-dir", str(project)]
    )
    assert result.returncode == 0, result.output


def test_a_project_with_everything_under_riskforge_deleted_warns_and_fails_strict(
    tmp_path: Path,
) -> None:
    _init(tmp_path)
    shutil.rmtree(tmp_path / ".riskforge")
    plain = _verify(tmp_path)
    assert plain.returncode == 0, plain.output
    assert NO_HEAD in plain.stderr
    strict = _verify(tmp_path, "--strict")
    assert strict.returncode == 2, strict.output
    assert len(_findings(strict)) == 1 and NO_HEAD in _findings(strict)[0]
    assert "—" not in plain.output + strict.output


def test_a_v113_system_classified_but_never_assessed_fails_strict(
    v113_project: tuple[Path, str],
) -> None:
    root, sid = v113_project
    log = root / ".riskforge" / "audit.jsonl"
    log.write_text(log.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
    for name in ("register.yaml", "mitigations.yaml"):
        (root / ".riskforge" / "systems" / sid / name).unlink()
    assert _verify(root).returncode == 0
    strict = _verify(root, "--strict")
    assert strict.returncode == 2, strict.output
    assert len(_findings(strict)) == 1 and NO_HEAD in _findings(strict)[0]


def test_strict_fails_on_the_empty_log_warning(v113_project: tuple[Path, str]) -> None:
    root, sid = v113_project
    (root / ".riskforge" / "audit.jsonl").unlink()
    register = root / ".riskforge" / "systems" / sid / "register.yaml"
    document = yaml.safe_load(register.read_text(encoding="utf-8"))
    document["items"] = []
    register.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    plain = _verify(root)
    assert plain.returncode == 0, plain.output
    assert "holds no entries" in plain.stderr
    strict = _verify(root, "--strict")
    assert strict.returncode == 2, strict.output
    findings = _findings(strict)
    assert len(findings) == 2, strict.stderr
    assert any(NO_HEAD in line for line in findings)
    assert any("The audit log holds no entries" in line for line in findings)
    assert "Integrity check failed with 2 findings:" in strict.stderr


def test_strict_on_a_recovery_view_lists_warnings_and_findings_and_keeps_the_note(
    v113_project: tuple[Path, str],
) -> None:
    root, sid = v113_project
    log = root / ".riskforge" / "audit.jsonl"
    last = json.loads(log.read_bytes().splitlines()[-1])
    journal = {"after_seq": last["seq"], "log_size": log.stat().st_size, "count": 1, "files": []}
    (root / ".riskforge" / "txn.json").write_text(json.dumps(journal), encoding="utf-8")
    system = root / ".riskforge" / "systems" / sid / "system.yaml"
    document = yaml.safe_load(system.read_text(encoding="utf-8"))
    document["name"] = "Renamed by hand"
    system.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    result = _verify(root, "--strict")
    assert result.returncode == 2, result.output
    findings = _findings(result)
    assert len(findings) == 3, result.stderr
    assert "differs from the copy in register.yaml" in findings[0]
    assert any(f"System {sid}: register.yaml {UNCOVERED}" in line for line in findings)
    assert any(NO_HEAD in line for line in findings)
    notes = [line for line in result.stderr.splitlines() if line.lstrip().startswith("!")]
    assert len(notes) == 1 and "checked as finishing or discarding" in notes[0]
    assert "—" not in result.output
