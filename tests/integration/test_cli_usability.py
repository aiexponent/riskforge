"""Usability findings 3, 6 and 7 of the 2.0.0 independent test."""

from __future__ import annotations

import re
from pathlib import Path

from rf_testkit import run_rf
from riskforge.models.system import AnnexIIICategory

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _help(*command: str) -> str:
    result = run_rf([*command, "--help"], env={"COLUMNS": "200"})
    assert result.returncode == 0, result.output
    return " ".join(result.output.replace("│", " ").split())


def test_init_help_lists_every_category() -> None:
    """Finding 3: `init --help` listed no allowed `--category` values."""
    text = _help("init")
    for category in AnnexIIICategory:
        assert category.value in text


def test_tests_generate_help_states_its_rule() -> None:
    """Finding 6: `tests generate --help` did not say which risks get a requirement."""
    text = _help("tests", "generate")
    assert "knowledge gap" in text
    assert "inherent score is 9 or more" in text


def test_risk_list_shows_the_residual_score(tmp_path: Path) -> None:
    """Finding 7: `risk list` showed only the inherent score, not the residual G3 uses."""
    answers = tmp_path / "answers.yaml"
    answers.write_text(
        "add_patterns: false\nanswers:\n  DI-001: { applies: yes, likelihood: 4, severity: 5 }\n"
    )
    project = tmp_path / "p"
    init = run_rf(
        [
            "init",
            "-n",
            "S",
            "-s",
            "1",
            "-p",
            "Purpose.",
            "--provider",
            "P",
            "-c",
            "essential_services",
            "--project-dir",
            str(project),
        ]
    )
    system_id = UUID_RE.search(init.output).group(0)
    assess = run_rf(
        ["assess", system_id, "-a", "A", "-r", "R", "--answers", str(answers)]
        + ["--project-dir", str(project)]
    )
    assert assess.returncode == 0, assess.output
    listed = run_rf(["risk", "list", system_id, "--project-dir", str(project)])
    risk_id = next(line for line in listed.output.splitlines() if "discrimination" in line)
    risk_id = re.search(r"[0-9a-f]{8}", risk_id).group(0)
    mitigate = run_rf(
        ["risk", "mitigate", system_id, risk_id, "-m", "Quarterly parity audit"]
        + ["-c", "detective", "--residual-likelihood", "2", "--residual-severity", "3"]
        + ["--owner", "ML team", "--by", "A", "--project-dir", str(project)]
    )
    assert mitigate.returncode == 0, mitigate.output
    listing = run_rf(["risk", "list", system_id, "--project-dir", str(project)])
    assert listing.returncode == 0, listing.output
    assert "Residual" in listing.output
    row = next(line for line in listing.output.splitlines() if "discrimination" in line)
    assert re.search(r"\b20\b.*\bcritical\b.*\b6\b", row), row
