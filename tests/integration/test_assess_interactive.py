"""Interactive `riskforge assess` driven through a real pseudo-terminal with pexpect (PRD-325)."""

from __future__ import annotations

import re
from pathlib import Path

import pexpect
import yaml
from rf_testkit import RF_BIN, offline_env, run_rf

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
APPLIES_KEY = {"yes": "1", "no": "2", "unknown": "3", "skip": "4"}
# Rich may style the numbers in the "Q<n>/<total>" progress line, so escape codes can sit
# between the digits.
MARKER = r"Q\d+/(?:\x1b\[[0-9;]*m)*\d+"


def _init(project: Path) -> str:
    result = run_rf(
        [
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
            "--project-dir",
            str(project),
        ]
    )
    assert result.returncode == 0, result.output
    match = UUID_RE.search(result.output)
    assert match, result.output
    return match.group(0)


def _spawn_assess(project: Path, system_id: str) -> pexpect.spawn:
    return pexpect.spawn(
        RF_BIN,
        [
            "assess",
            system_id,
            "-a",
            "Alice Chen",
            "-r",
            "AI Governance Lead",
            "--dimension",
            "privacy",
            "--project-dir",
            str(project),
        ],
        # Without PROMPT_TOOLKIT_NO_CPR, questionary asks the terminal for its cursor
        # position, pexpect never answers, and keys typed during the wait are dropped.
        env=offline_env({"TERM": "xterm-256color", "PROMPT_TOOLKIT_NO_CPR": "1"}),
        encoding="utf-8",
        timeout=30,
        dimensions=(40, 120),
    )


def _answer(child: pexpect.spawn, applies: str, likelihood: int = 0, severity: int = 0) -> None:
    # questionary redraws a prompt after it is answered, so the prompt text shows up twice.
    # Wait for RiskForge's progress line (printed once per question) and the full menu.
    child.expect(MARKER)
    child.expect(r"4\) skip")
    child.send(APPLIES_KEY[applies])
    child.send("\r")
    if applies == "yes":
        child.expect("Likelihood")
        child.expect(r"5\) ")
        child.send(str(likelihood))
        child.send("\r")
        child.expect("Severity")
        child.expect(r"5\) ")
        child.send(str(severity))
        child.send("\r")


def _finish(child: pexpect.spawn) -> None:
    child.expect(pexpect.EOF)
    child.close()
    assert child.exitstatus == 0, child.before


def _items(project: Path) -> list[dict]:
    register = next((project / ".riskforge" / "systems").glob("*/register.yaml"))
    return yaml.safe_load(register.read_text(encoding="utf-8"))["items"]


def test_interactive_assess_saves_each_answer(tmp_path: Path) -> None:
    system_id = _init(tmp_path)
    child = _spawn_assess(tmp_path, system_id)
    try:
        child.expect(r"Add pattern-derived risk items.*\(Y/n\)")
        child.send("\r")
        _answer(child, "yes", 4, 5)
        for applies in ("no", "unknown", "skip", "no"):
            _answer(child, applies)
        child.expect("Assessment Session Complete")
        _finish(child)
    finally:
        child.close(force=True)
    items = _items(tmp_path)
    assert [(i["source"], i["tags"]) for i in items] == [
        ("pattern", ["pattern:CREDIT_SCORING_BIAS"]),
        ("pattern", ["pattern:CREDIT_SCORING_BIAS"]),
        ("question_bank", ["PR-001"]),
        ("question_bank", ["PR-003"]),
    ]
    assert (items[2]["likelihood"], items[2]["severity"]) == (4, 5)
    assert items[3]["knowledge_gap"] is True
    verify = run_rf(["verify", "--project-dir", str(tmp_path)])
    assert verify.returncode == 0, verify.output


def test_ctrl_c_keeps_answers_given_so_far(tmp_path: Path) -> None:
    system_id = _init(tmp_path)
    child = _spawn_assess(tmp_path, system_id)
    try:
        child.expect(r"Add pattern-derived risk items.*\(Y/n\)")
        child.send("\r")
        _answer(child, "yes", 4, 5)
        child.expect(MARKER)
        child.expect(r"4\) skip")
        child.sendcontrol("c")
        child.expect("Session interrupted")
        _finish(child)
    finally:
        child.close(force=True)
    assert len(_items(tmp_path)) == 3
    verify = run_rf(["verify", "--project-dir", str(tmp_path)])
    assert verify.returncode == 0, verify.output


def test_ctrl_c_at_pattern_prompt_stops_the_session(tmp_path: Path) -> None:
    system_id = _init(tmp_path)
    child = _spawn_assess(tmp_path, system_id)
    try:
        child.expect(r"Add pattern-derived risk items.*\(Y/n\)")
        child.sendcontrol("c")
        # Fail fast if Ctrl+C is read as "no" and the questions start.
        shown = child.expect(["Session interrupted", MARKER])
        assert shown == 0, "a question prompt was shown after Ctrl+C at the pattern prompt"
        child.expect(pexpect.EOF)
        rest = child.before
        child.close()
        assert child.exitstatus == 0, rest
    finally:
        child.close(force=True)
    assert not re.search(MARKER, rest), rest
    assert "Does this risk apply" not in rest
    assert "Traceback" not in rest
    assert _items(tmp_path) == []
    verify = run_rf(["verify", "--project-dir", str(tmp_path)])
    assert verify.returncode == 0, verify.output


def test_rerun_after_interrupt_adds_no_duplicates(tmp_path: Path) -> None:
    system_id = _init(tmp_path)
    log = tmp_path / ".riskforge" / "audit.jsonl"
    logs: list[bytes] = []
    for _session in range(2):
        child = _spawn_assess(tmp_path, system_id)
        try:
            child.expect(r"Add pattern-derived risk items.*\(Y/n\)")
            child.send("\r")
            _answer(child, "yes", 4, 5)
            child.expect(MARKER)
            child.expect(r"4\) skip")
            child.sendcontrol("c")
            child.expect("Session interrupted")
            _finish(child)
        finally:
            child.close(force=True)
        logs.append(log.read_bytes())
    assert [(i["source"], i["tags"]) for i in _items(tmp_path)] == [
        ("pattern", ["pattern:CREDIT_SCORING_BIAS"]),
        ("pattern", ["pattern:CREDIT_SCORING_BIAS"]),
        ("question_bank", ["PR-001"]),
    ]
    assert logs[1] == logs[0]
    verify = run_rf(["verify", "--project-dir", str(tmp_path)])
    assert verify.returncode == 0, verify.output
