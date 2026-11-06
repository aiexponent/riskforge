"""Who the audit log names for each write command (D10 of the 2.0.0 independent test).

In one project the log named `cli` for init, classify, tests generate and export, the
assessor for assess, and the `--by` text for risk accept. Every write command without a
name of its own now records RISKFORGE_ACTOR when it is set, and `cli` otherwise.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from rf_testkit import run_rf

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
INIT = [
    "init",
    "-n",
    "Loan Scoring Model",
    "-s",
    "2.1",
    "-p",
    "Automated credit scoring for retail loan applications.",
    "--provider",
    "Acme Financial Services",
    "-c",
    "essential_services",
]


def _actors(project: Path) -> list[str]:
    path = project / ".riskforge" / "audit.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["actor"]["identity"] for line in lines]


def _actors_by_command(project: Path, env: dict[str, str] | None) -> dict[str, set[str]]:
    """The actors of the audit entries each command wrote."""
    by_command: dict[str, set[str]] = {}

    def rf(name: str, *args: str) -> str:
        before = len(_actors(project))
        result = run_rf([*args, "--project-dir", str(project)], env=env)
        assert result.returncode == 0, result.output
        by_command[name] = set(_actors(project)[before:])
        assert by_command[name], f"{name} wrote no audit entry"
        return result.output

    answers = project.parent / f"{project.name}-answers.yaml"
    answers.write_text("add_patterns: false\nanswers:\n  DI-001: { applies: unknown }\n")
    system_id = UUID_RE.search(rf("init", *INIT)).group(0)
    rf("classify", "system", "classify", system_id, "--confirm")
    rf("assess", "assess", system_id, "-a", "Alice Chen", "-r", "Lead", "--answers", str(answers))
    rf("tests", "tests", "generate", system_id)
    rf("export", "export", system_id, "-o", str(project / "rmf.json"), "--force")
    return by_command


def test_every_write_command_records_riskforge_actor(tmp_path: Path) -> None:
    actors = _actors_by_command(tmp_path, {"RISKFORGE_ACTOR": "Mara Lindqvist"})
    assert actors.pop("assess") == {"Alice Chen"}, "assess keeps its -a name"
    assert actors == dict.fromkeys(actors, {"Mara Lindqvist"})


def test_without_riskforge_actor_the_actor_is_cli(tmp_path: Path) -> None:
    actors = _actors_by_command(tmp_path, None)
    assert actors.pop("assess") == {"Alice Chen"}
    assert actors == dict.fromkeys(actors, {"cli"})


def test_a_riskforge_actor_with_a_line_break_is_refused(tmp_path: Path) -> None:
    result = run_rf([*INIT, "--project-dir", str(tmp_path)], env={"RISKFORGE_ACTOR": "a\nb"})
    assert result.returncode == 3, result.output
    assert "RISKFORGE_ACTOR" in result.output
    assert _actors(tmp_path) == []
