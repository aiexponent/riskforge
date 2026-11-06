"""`init` and `system describe` record the system description (D7 of the 2.0.0 test)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml
from rf_testkit import run_rf

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
BASE = ["init", "-n", "X", "-s", "1", "-p", "credit scoring", "--provider", "P"]


def _init(project: Path, *extra: str) -> str:
    result = run_rf([*BASE, *extra, "--project-dir", str(project)])
    assert result.returncode == 0, result.output
    return UUID_RE.search(result.output).group(0)


def _assess(project: Path, sid: str) -> None:
    answers = project / "a.yaml"
    answers.write_text(
        "add_patterns: false\nanswers:\n  PR-001: { applies: yes, likelihood: 2, severity: 2 }\n"
    )
    result = run_rf(
        ["assess", sid, "-a", "A", "-r", "B", "--answers", str(answers)]
        + ["--project-dir", str(project)]
    )
    assert result.returncode == 0, result.output


def _system(project: Path, sid: str) -> dict:
    path = project / ".riskforge" / "systems" / sid / "system.yaml"
    return yaml.safe_load(path.read_text())


def _register_system(project: Path, sid: str) -> dict:
    path = project / ".riskforge" / "systems" / sid / "register.yaml"
    return yaml.safe_load(path.read_text())["system"]


def _events(project: Path) -> list[dict]:
    lines = (project / ".riskforge" / "audit.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


def _g5(project: Path, sid: str) -> dict:
    out = project / "rmf.json"
    result = run_rf(["export", sid, "-o", str(out), "--force", "--project-dir", str(project)])
    assert result.returncode == 0, result.output
    gates = json.loads(out.read_text())["validation"]["gates"]
    return next(g for g in gates if g["gate_id"] == "G5")


def test_init_records_the_description(tmp_path: Path) -> None:
    sid = _init(
        tmp_path,
        "--intended-user", "Underwriters", "--intended-user", "Analysts",
        "--input", "Application", "--output", "Score",
        "--deployment-context", "Retail lending", "--provider-contact", "a@example.com",
    )  # fmt: skip
    system = _system(tmp_path, sid)
    assert system["intended_users"] == ["Underwriters", "Analysts"]
    assert (system["inputs"], system["outputs"]) == (["Application"], ["Score"])
    assert system["deployment_context"] == "Retail lending"
    assert system["provider_contact"] == "a@example.com"
    _assess(tmp_path, sid)
    assert _g5(tmp_path, sid)["status"] == "PASS"


def test_an_empty_description_warns_in_the_signed_file(tmp_path: Path) -> None:
    sid = _init(tmp_path)
    _assess(tmp_path, sid)
    gate = _g5(tmp_path, sid)
    assert gate["status"] == "WARN"
    assert (
        "intended_users, inputs, outputs, deployment_context, provider_contact" in (gate["details"])
    )


def test_describe_updates_the_system_and_its_register_and_is_audited(tmp_path: Path) -> None:
    sid = _init(tmp_path, "--input", "Old input")
    _assess(tmp_path, sid)
    result = run_rf(
        ["system", "describe", sid, "--input", "Application", "--input", "Bureau report"]
        + ["--deployment-context", "Retail lending", "--project-dir", str(tmp_path)]
    )
    assert result.returncode == 0, result.output
    for system in (_system(tmp_path, sid), _register_system(tmp_path, sid)):
        assert system["inputs"] == ["Application", "Bureau report"]
        assert system["deployment_context"] == "Retail lending"
        assert system["outputs"] == []
    last = _events(tmp_path)[-1]
    assert last["event"] == "system.described"
    assert last["payload"] == {
        "changed": {
            "inputs": ["Application", "Bureau report"],
            "deployment_context": "Retail lending",
        }
    }
    assert run_rf(["verify", "--project-dir", str(tmp_path)]).returncode == 0


def test_describe_with_the_same_values_records_nothing(tmp_path: Path) -> None:
    sid = _init(tmp_path, "--deployment-context", "Retail lending")
    before = len(_events(tmp_path))
    result = run_rf(
        ["system", "describe", sid, "--deployment-context", "Retail lending"]
        + ["--project-dir", str(tmp_path)]
    )
    assert result.returncode == 0, result.output
    assert "already matches" in result.output
    assert len(_events(tmp_path)) == before


def test_describe_without_an_option_exits_3(tmp_path: Path) -> None:
    sid = _init(tmp_path)
    before = len(_events(tmp_path))
    result = run_rf(["system", "describe", sid, "--project-dir", str(tmp_path)])
    assert result.returncode == 3, result.output
    assert len(_events(tmp_path)) == before
