"""assess adds the pattern that the system's purpose phrase names (PRD-335)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from rf_testkit import run_rf

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _pattern_tags(project: Path, purpose: str, category: str | None) -> set[str]:
    init_args = ["init", "-n", "X", "-s", "1", "-p", purpose, "--provider", "P"]
    if category:
        init_args += ["-c", category]
    init = run_rf([*init_args, "--project-dir", str(project)])
    assert init.returncode == 0, init.output
    sid = UUID_RE.search(init.output).group(0)
    answers = project / "answers.yaml"
    answers.write_text("add_patterns: true\nanswers: {}\n", encoding="utf-8")
    assess = run_rf(
        ["assess", sid, "-a", "A", "-r", "B", "--answers", str(answers)]
        + ["--project-dir", str(project)]
    )
    assert assess.returncode == 0, assess.output
    register = next((project / ".riskforge" / "systems").glob("*/register.yaml"))
    items = yaml.safe_load(register.read_text(encoding="utf-8"))["items"]
    return {tag for item in items for tag in item["tags"] if tag.startswith("pattern:")}


@pytest.mark.parametrize(
    ("purpose", "category", "expected"),
    [
        ("Facial recognition of travellers", "biometric", {"pattern:LAW_ENFORCEMENT_BIOMETRIC"}),
        (
            "Creditworthiness checks for loans",
            "essential_services",
            {"pattern:CREDIT_SCORING_BIAS"},
        ),
        ("Diagnostic support for chest radiology images", None, {"pattern:MEDICAL_DIAGNOSIS"}),
        ("Patient appointment scheduling for clinics", None, set()),
    ],
)
def test_assess_adds_the_pattern_the_purpose_names(
    tmp_path: Path, purpose: str, category: str | None, expected: set[str]
) -> None:
    assert _pattern_tags(tmp_path, purpose, category) == expected
