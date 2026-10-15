"""Every CLI change leaves an audit entry, starting with init (PRD-331)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from rf_testkit import run_rf

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _events(project: Path) -> list[str]:
    lines = (project / ".riskforge" / "audit.jsonl").read_text().splitlines()
    return [json.loads(line)["event"] for line in lines]


def test_init_classify_and_assess_are_recorded(tmp_path: Path) -> None:
    result = run_rf(
        [
            "init",
            "-n",
            "S",
            "-s",
            "1",
            "-p",
            "resume screening for hiring",
            "--provider",
            "Müller GmbH",
            "-c",
            "employment",
            "--project-dir",
            str(tmp_path),
        ]
    )
    assert result.returncode == 0, result.output
    sid = UUID_RE.search(result.output).group(0)
    assert _events(tmp_path) == ["system.created"]

    classified = run_rf(["system", "classify", sid, "--confirm", "--project-dir", str(tmp_path)])
    assert classified.returncode == 0, classified.output

    answers = tmp_path / "answers.yaml"
    answers.write_text(
        "add_patterns: false\nanswers:\n  PR-001: { applies: yes, likelihood: 2, severity: 2 }\n"
    )
    assess_args = ["assess", sid, "-a", "A", "-r", "B", "--answers", str(answers)]
    assessed = run_rf([*assess_args, "--project-dir", str(tmp_path)])
    assert assessed.returncode == 0, assessed.output
    assert _events(tmp_path) == [
        "system.created",
        "system.classified",
        "register.created",
        "risk_item.created",
    ]

    rerun = run_rf([*assess_args, "--project-dir", str(tmp_path)])
    assert rerun.returncode == 0, rerun.output
    assert _events(tmp_path).count("register.created") == 1

    verified = run_rf(["verify", "--project-dir", str(tmp_path)])
    assert verified.returncode == 0, verified.output
    assert not (tmp_path / ".riskforge" / "txn.json").exists()
    assert not list(tmp_path.rglob("*.pending"))
