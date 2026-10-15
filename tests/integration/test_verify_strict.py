"""riskforge verify --strict: warnings about missing fingerprint coverage fail with exit 2."""

from __future__ import annotations

from pathlib import Path

import yaml
from rf_testkit import run_rf

UNCOVERED = "is not covered by a fingerprint yet"


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
    assert len(findings) == 1, result.stderr
    assert f"System {sid}: register.yaml {UNCOVERED}" in findings[0]
    assert "Integrity check failed with 1 finding:" in result.stderr
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
