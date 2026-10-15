"""riskforge diff lists added, removed and changed items, field by field (PRD-343)."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from rf_testkit import run_rf

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "v1_1_3_project" / "rmf.json"
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _export(project: Path, sid: str, out: Path) -> dict:
    result = run_rf(["export", sid, "-o", str(out), "--force", "--project-dir", str(project)])
    assert result.returncode == 0, result.output
    return json.loads(out.read_text(encoding="utf-8"))


def test_diff_shows_a_residual_change_between_two_exports(tmp_path: Path) -> None:
    init = run_rf(
        ["init", "-n", "X", "-s", "1", "-p", "credit scoring for loans", "--provider", "P"]
        + ["-c", "essential_services", "--project-dir", str(tmp_path)]
    )
    assert init.returncode == 0, init.output
    sid = UUID_RE.search(init.output).group(0)
    answers = tmp_path / "answers.yaml"
    answers.write_text(
        "add_patterns: false\nanswers:\n  PR-001: { applies: yes, likelihood: 4, severity: 4 }\n"
    )
    assess = run_rf(
        ["assess", sid, "-a", "A", "-r", "B", "--answers", str(answers)]
        + ["--project-dir", str(tmp_path)]
    )
    assert assess.returncode == 0, assess.output
    v1, v2 = tmp_path / "v1.json", tmp_path / "v2.json"
    item = _export(tmp_path, sid, v1)["register"]["items"][0]
    mitigate = run_rf(
        ["risk", "mitigate", sid, item["id"][:8], "-m", "Block release above a 0.10 parity gap"]
        + ["-c", "preventive", "--owner", "ML team", "--by", "Jane Doe, Head of AI"]
        + ["--residual-likelihood", "1", "--residual-severity", "2"]
        + ["--project-dir", str(tmp_path)]
    )
    assert mitigate.returncode == 0, mitigate.output
    _export(tmp_path, sid, v2)

    result = run_rf(["diff", sid, str(v1), str(v2)])

    assert result.returncode == 0, result.output
    assert "+0 added  -0 removed  ~1 changed" in result.output, result.output
    assert f"~ {item['id'][:8]} " in result.output
    assert f"residual_likelihood: {item['residual_likelihood']} -> 1" in result.output
    assert f"residual_severity: {item['residual_severity']} -> 2" in result.output
    assert "mitigations: 0 -> 1" in result.output


def test_diff_prints_bracketed_titles_literally(tmp_path: Path) -> None:
    old = json.loads(FIXTURE.read_text(encoding="utf-8"))
    old["register"]["items"][0]["title"] = "[draft] Bias"
    new = copy.deepcopy(old)
    new["register"]["items"][0]["residual_likelihood"] = 1
    added = copy.deepcopy(new["register"]["items"][0])
    added["id"] = "bbbbbbbb-0000-0000-0000-000000000002"
    added["title"] = "[bold]New[/bold] risk"
    new["register"]["items"].append(added)
    v1, v2 = tmp_path / "v1.json", tmp_path / "v2.json"
    v1.write_text(json.dumps(old), encoding="utf-8")
    v2.write_text(json.dumps(new), encoding="utf-8")

    result = run_rf(["diff", old["register"]["system"]["id"], str(v1), str(v2)])

    assert result.returncode == 0, result.output
    assert "+1 added  -0 removed  ~1 changed" in result.output, result.output
    assert "[draft] Bias" in result.output
    assert "bbbbbbbb [bold]New[/bold] risk" in result.output


def test_diff_of_identical_files_reports_no_changes() -> None:
    sid = json.loads(FIXTURE.read_text(encoding="utf-8"))["register"]["system"]["id"]
    result = run_rf(["diff", sid, str(FIXTURE), str(FIXTURE)])
    assert result.returncode == 0, result.output
    assert result.stdout.strip() == "+0 added  -0 removed  ~0 changed"


def test_diff_refuses_files_from_another_system() -> None:
    other = "00000000-0000-0000-0000-000000000000"
    result = run_rf(["diff", other, str(FIXTURE), str(FIXTURE)])
    assert result.returncode == 3, result.output
    assert "belongs to system" in result.output
    assert "Traceback" not in result.output


def test_diff_refuses_a_register_without_an_item_list(tmp_path: Path) -> None:
    broken = json.loads(FIXTURE.read_text(encoding="utf-8"))
    broken["register"]["items"] = {"not": "a list"}
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(broken), encoding="utf-8")
    result = run_rf(["diff", broken["register"]["system"]["id"], str(path), str(FIXTURE)])
    assert result.returncode == 3, result.output
    assert "Traceback" not in result.output
