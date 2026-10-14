"""assess --answers is idempotent; a changed answer updates the matching item (PRD-334)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from rf_testkit import run_rf

REPO = Path(__file__).resolve().parents[2]
ANSWERS = REPO / "examples" / "credit-scoring" / "answers.yaml"
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _init(project: Path) -> str:
    result = run_rf(
        [
            "init",
            "-n",
            "CreditFlow",
            "-s",
            "2.1.0",
            "-p",
            "Automated credit scoring for retail loan and mortgage underwriting decisions.",
            "--provider",
            "Acme",
            "-c",
            "essential_services",
            "--project-dir",
            str(project),
        ]
    )
    assert result.returncode == 0, result.output
    match = UUID_RE.search(result.output)
    assert match, result.output
    return match.group(0)


def _assess(project: Path, sid: str, answers: Path):
    return run_rf(
        [
            "assess",
            sid,
            "-a",
            "Alice",
            "-r",
            "Lead",
            "--answers",
            str(answers),
            "--project-dir",
            str(project),
        ]
    )


def _register_path(project: Path) -> Path:
    return next((project / ".riskforge" / "systems").glob("*/register.yaml"))


def _items(project: Path) -> list[dict]:
    return yaml.safe_load(_register_path(project).read_text(encoding="utf-8"))["items"]


def _item(project: Path, tag: str) -> dict:
    return next(i for i in _items(project) if i["tags"] == [tag])


def _entries(project: Path) -> list[dict]:
    log = (project / ".riskforge" / "audit.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in log.splitlines()]


def _snapshot(project: Path) -> dict[str, bytes]:
    """Every file under .riskforge/ by relative path, except the two any command creates.

    ``audit.lock`` and ``.nodelete`` are written when a command opens the project; the
    1.1.3 fixture has neither.
    """
    root = project / ".riskforge"
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name not in {"audit.lock", ".nodelete"}
    }


def _answers_with(tmp_path: Path, **changes: dict) -> Path:
    document = yaml.safe_load(ANSWERS.read_text(encoding="utf-8"))
    for qid, answer in changes.items():
        document["answers"][qid.replace("_", "-")] = answer
    path = tmp_path / "answers-changed.yaml"
    path.write_text(yaml.dump(document, sort_keys=False), encoding="utf-8")
    return path


def test_same_answers_twice_change_nothing(tmp_path: Path) -> None:
    sid = _init(tmp_path)
    first_run = _assess(tmp_path, sid, ANSWERS)
    assert first_run.returncode == 0, first_run.output
    before = _snapshot(tmp_path)
    second_run = _assess(tmp_path, sid, ANSWERS)
    assert second_run.returncode == 0, second_run.output
    assert "0 added, 0 updated, 10 unchanged" in second_run.output, second_run.output
    assert "Total in register: 10." in second_run.output
    assert "nothing is duplicated" in second_run.output
    assert _snapshot(tmp_path) == before
    assert run_rf(["verify", "--project-dir", str(tmp_path)]).returncode == 0


def test_changed_score_updates_the_matching_item(tmp_path: Path) -> None:
    sid = _init(tmp_path)
    assert _assess(tmp_path, sid, ANSWERS).returncode == 0
    before = _item(tmp_path, "DI-001")
    entries_before = _entries(tmp_path)
    changed = _answers_with(tmp_path, DI_001={"applies": "yes", "likelihood": 2, "severity": 5})
    result = _assess(tmp_path, sid, changed)
    assert result.returncode == 0, result.output
    assert "0 added, 1 updated, 9 unchanged" in result.output, result.output
    item = _item(tmp_path, "DI-001")
    assert item["id"] == before["id"]
    assert (item["likelihood"], item["severity"]) == (2, 5)
    assert (item["residual_likelihood"], item["residual_severity"]) == (2, 5)
    assert len(_items(tmp_path)) == 10
    new_entries = _entries(tmp_path)[len(entries_before) :]
    assert [e["event"] for e in new_entries] == ["risk_item.updated"]
    assert new_entries[0]["payload"] == {
        "risk_item_id": item["id"],
        "old_score": 20,
        "new_score": 10,
        "reason": "reassessment",
    }
    assert run_rf(["verify", "--project-dir", str(tmp_path)]).returncode == 0


def test_unknown_then_yes_clears_the_knowledge_gap(tmp_path: Path) -> None:
    sid = _init(tmp_path)
    assert _assess(tmp_path, sid, ANSWERS).returncode == 0
    assert _item(tmp_path, "DG-001")["knowledge_gap"] is True
    changed = _answers_with(tmp_path, DG_001={"applies": "yes", "likelihood": 2, "severity": 3})
    result = _assess(tmp_path, sid, changed)
    assert "0 added, 1 updated, 9 unchanged" in result.output, result.output
    item = _item(tmp_path, "DG-001")
    assert item["knowledge_gap"] is False
    assert (item["likelihood"], item["severity"]) == (2, 3)


def test_changed_score_on_a_mitigated_item_keeps_its_residual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Names the actor for a `risk mitigate` that requires one (PRD-356); ignored otherwise.
    monkeypatch.setenv("RISKFORGE_ACTOR", "Alice, Lead")
    sid = _init(tmp_path)
    assert _assess(tmp_path, sid, ANSWERS).returncode == 0
    target = _item(tmp_path, "DI-001")
    mitigated = run_rf(
        [
            "risk",
            "mitigate",
            sid,
            target["id"][:8],
            "-m",
            "Quarterly disparate impact test on held-out applicants, signed off by the DPO.",
            "-c",
            "detective",
            "--owner",
            "Model Risk",
            "--residual-likelihood",
            "2",
            "--residual-severity",
            "4",
            "--project-dir",
            str(tmp_path),
        ]
    )
    assert mitigated.returncode == 0, mitigated.output
    changed = _answers_with(tmp_path, DI_001={"applies": "yes", "likelihood": 5, "severity": 5})
    result = _assess(tmp_path, sid, changed)
    assert "review its residual score and acceptance" in result.output, result.output
    item = _item(tmp_path, "DI-001")
    assert (item["likelihood"], item["severity"]) == (5, 5)
    assert (item["residual_likelihood"], item["residual_severity"]) == (2, 4)
    assert len(item["mitigations"]) == 1


def test_changed_score_on_an_accepted_item_keeps_the_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Names the actor for a `risk accept` that requires one (PRD-356); ignored otherwise.
    monkeypatch.setenv("RISKFORGE_ACTOR", "Alice, Lead")
    sid = _init(tmp_path)
    assert _assess(tmp_path, sid, ANSWERS).returncode == 0
    target = _item(tmp_path, "DI-001")
    accepted = run_rf(
        ["risk", "accept", sid, target["id"][:8], "-r", "Reviewed.", "--project-dir", str(tmp_path)]
    )
    assert accepted.returncode == 0, accepted.output
    changed = _answers_with(tmp_path, DI_001={"applies": "yes", "likelihood": 5, "severity": 5})
    result = _assess(tmp_path, sid, changed)
    assert result.returncode == 0, result.output
    assert target["id"][:8] in result.output
    assert "review its residual score and acceptance" in result.output, result.output
    item = _item(tmp_path, "DI-001")
    assert item["accepted"] is True
    assert item["acceptance_rationale"] == "Reviewed."
    assert (item["likelihood"], item["severity"]) == (5, 5)


def test_answer_changed_to_no_keeps_the_item(tmp_path: Path) -> None:
    sid = _init(tmp_path)
    assert _assess(tmp_path, sid, ANSWERS).returncode == 0
    before = _snapshot(tmp_path)
    changed = _answers_with(tmp_path, PR_001={"applies": "no"}, HO_001={"applies": "skip"})
    result = _assess(tmp_path, sid, changed)
    assert result.returncode == 0, result.output
    assert "HO-001, PR-001" in result.output and "never removes" in result.output, result.output
    assert _item(tmp_path, "PR-001")["likelihood"] == 3
    assert _item(tmp_path, "HO-001")["likelihood"] == 2
    assert _snapshot(tmp_path) == before


def test_items_written_by_v113_are_recognised(v113_project: tuple[Path, str]) -> None:
    root, sid = v113_project
    before = _snapshot(root)
    result = _assess(root, sid, ANSWERS)
    assert result.returncode == 0, result.output
    assert "0 added, 0 updated, 10 unchanged" in result.output, result.output
    assert _snapshot(root) == before
