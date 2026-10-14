"""`risk accept` and `risk mitigate` record who did it (PRD-356).

The name comes from `--by` or, when the flag is absent, from RISKFORGE_ACTOR. Neither
is a usage error (exit 3). The value is the audit entry's actor identity and is stored
on the item (`accepted_by`) or the mitigation (`recorded_by`).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from rf_testkit import run_rf

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
JANE = "Jane Doe, Head of AI"


def _init_and_assess(project: Path) -> tuple[str, str]:
    """Return (system id, full id of the first risk item)."""
    init = run_rf(
        ["init", "-n", "X", "-s", "1", "-p", "credit scoring for loans", "--provider", "P"]
        + ["-c", "essential_services", "--project-dir", str(project)]
    )
    assert init.returncode == 0, init.output
    sid = UUID_RE.search(init.output).group(0)
    answers = project / "answers.yaml"
    answers.write_text(
        "add_patterns: false\nanswers:\n  PR-001: { applies: yes, likelihood: 4, severity: 4 }\n"
    )
    assess = run_rf(
        ["assess", sid, "-a", "A", "-r", "B", "--answers", str(answers)]
        + ["--project-dir", str(project)]
    )
    assert assess.returncode == 0, assess.output
    return sid, _register(project, sid)["items"][0]["id"]


def _register_path(project: Path, sid: str) -> Path:
    return project / ".riskforge" / "systems" / sid / "register.yaml"


def _register(project: Path, sid: str) -> dict:
    return yaml.safe_load(_register_path(project, sid).read_text(encoding="utf-8"))


def _last_entry(project: Path) -> dict:
    lines = (project / ".riskforge" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    return json.loads(lines[-1])


def _accept(project: Path, sid: str, rid: str, *extra: str, env: dict | None = None):
    args = ["risk", "accept", sid, rid[:8], "-r", "Residual within appetite."]
    return run_rf([*args, *extra, "--project-dir", str(project)], env=env)


def _mitigate(project: Path, sid: str, rid: str, *extra: str, env: dict | None = None):
    args = ["risk", "mitigate", sid, rid[:8], "-m", "Block release above a 0.10 parity gap"]
    args += ["-c", "preventive", "--owner", "ML team"]
    return run_rf([*args, *extra, "--project-dir", str(project)], env=env)


def _assert_missing_actor(result, project: Path, sid: str, before: bytes) -> None:
    assert result.returncode == 3, result.output
    assert "Traceback" not in result.output, result.output
    lines = result.stderr.strip().splitlines()
    assert len(lines) == 1, result.stderr
    assert "--by" in lines[0] and "RISKFORGE_ACTOR" in lines[0], lines[0]
    assert _register_path(project, sid).read_bytes() == before


# --- risk accept --------------------------------------------------------------------


def test_accept_without_by_or_env_exits_3(tmp_path: Path) -> None:
    sid, rid = _init_and_assess(tmp_path)
    before = _register_path(tmp_path, sid).read_bytes()
    _assert_missing_actor(_accept(tmp_path, sid, rid), tmp_path, sid, before)


@pytest.mark.parametrize("value", ["", "   "])
def test_accept_with_blank_actor_exits_3(tmp_path: Path, value: str) -> None:
    sid, rid = _init_and_assess(tmp_path)
    before = _register_path(tmp_path, sid).read_bytes()
    result = _accept(tmp_path, sid, rid, "--by", value, env={"RISKFORGE_ACTOR": value})
    _assert_missing_actor(result, tmp_path, sid, before)


def test_accept_rejects_a_multi_line_name(tmp_path: Path) -> None:
    sid, rid = _init_and_assess(tmp_path)
    before = _register_path(tmp_path, sid).read_bytes()
    result = _accept(tmp_path, sid, rid, "--by", "Jane Doe\nHead of AI")
    assert result.returncode == 3, result.output
    assert len(result.stderr.strip().splitlines()) == 1, result.stderr
    assert "--by" in result.stderr
    assert _register_path(tmp_path, sid).read_bytes() == before


def test_accept_with_by_records_the_name(tmp_path: Path) -> None:
    sid, rid = _init_and_assess(tmp_path)
    result = _accept(tmp_path, sid, rid, "--by", f"  {JANE} ")
    assert result.returncode == 0, result.output
    entry = _last_entry(tmp_path)
    assert entry["event"] == "risk.accepted"
    assert entry["actor"] == {"type": "human", "identity": JANE}
    assert entry["payload"]["actor"] == JANE
    item = _register(tmp_path, sid)["items"][0]
    assert item["accepted"] is True
    assert item["accepted_by"] == JANE


def test_accept_takes_the_name_from_the_environment(tmp_path: Path) -> None:
    sid, rid = _init_and_assess(tmp_path)
    result = _accept(tmp_path, sid, rid, env={"RISKFORGE_ACTOR": "CI Bot, Release Pipeline"})
    assert result.returncode == 0, result.output
    assert _last_entry(tmp_path)["actor"]["identity"] == "CI Bot, Release Pipeline"
    assert _register(tmp_path, sid)["items"][0]["accepted_by"] == "CI Bot, Release Pipeline"


def test_accept_flag_overrides_the_environment(tmp_path: Path) -> None:
    sid, rid = _init_and_assess(tmp_path)
    result = _accept(tmp_path, sid, rid, "--by", JANE, env={"RISKFORGE_ACTOR": "Someone Else"})
    assert result.returncode == 0, result.output
    assert _last_entry(tmp_path)["actor"]["identity"] == JANE
    assert _register(tmp_path, sid)["items"][0]["accepted_by"] == JANE


def test_verify_passes_after_accept_and_fails_when_accepted_by_is_edited(tmp_path: Path) -> None:
    sid, rid = _init_and_assess(tmp_path)
    assert _accept(tmp_path, sid, rid, "--by", JANE).returncode == 0
    verified = run_rf(["verify", "--project-dir", str(tmp_path)])
    assert verified.returncode == 0, verified.output

    path = _register_path(tmp_path, sid)
    text = path.read_text(encoding="utf-8")
    assert f"accepted_by: {JANE}" in text
    path.write_text(text.replace(JANE, "Somebody Else, CEO"), encoding="utf-8")
    tampered = run_rf(["verify", "--project-dir", str(tmp_path)])
    assert tampered.returncode == 2, tampered.output


# --- risk mitigate ------------------------------------------------------------------


def test_mitigate_without_by_or_env_exits_3(tmp_path: Path) -> None:
    sid, rid = _init_and_assess(tmp_path)
    before = _register_path(tmp_path, sid).read_bytes()
    _assert_missing_actor(_mitigate(tmp_path, sid, rid), tmp_path, sid, before)


def test_mitigate_with_by_records_the_name(tmp_path: Path) -> None:
    sid, rid = _init_and_assess(tmp_path)
    result = _mitigate(tmp_path, sid, rid, "--by", JANE)
    assert result.returncode == 0, result.output
    entry = _last_entry(tmp_path)
    assert entry["event"] == "mitigation.added"
    assert entry["actor"] == {"type": "human", "identity": JANE}
    mitigation = _register(tmp_path, sid)["items"][0]["mitigations"][-1]
    assert mitigation["recorded_by"] == JANE


def test_mitigate_takes_the_name_from_the_environment(tmp_path: Path) -> None:
    sid, rid = _init_and_assess(tmp_path)
    result = _mitigate(tmp_path, sid, rid, env={"RISKFORGE_ACTOR": "CI Bot, Release Pipeline"})
    assert result.returncode == 0, result.output
    assert _last_entry(tmp_path)["actor"]["identity"] == "CI Bot, Release Pipeline"
    mitigation = _register(tmp_path, sid)["items"][0]["mitigations"][-1]
    assert mitigation["recorded_by"] == "CI Bot, Release Pipeline"


def test_mitigate_flag_overrides_the_environment(tmp_path: Path) -> None:
    sid, rid = _init_and_assess(tmp_path)
    result = _mitigate(tmp_path, sid, rid, "--by", JANE, env={"RISKFORGE_ACTOR": "Someone Else"})
    assert result.returncode == 0, result.output
    assert _last_entry(tmp_path)["actor"]["identity"] == JANE
    assert _register(tmp_path, sid)["items"][0]["mitigations"][-1]["recorded_by"] == JANE


# --- exports ------------------------------------------------------------------------


def test_markdown_export_shows_who_accepted_and_who_recorded(tmp_path: Path) -> None:
    sid, rid = _init_and_assess(tmp_path)
    assert _mitigate(tmp_path, sid, rid, "--by", "Sam Lee, ML Lead").returncode == 0
    assert _accept(tmp_path, sid, rid, "--by", JANE).returncode == 0
    out = tmp_path / "rmf.md"
    result = run_rf(
        ["export", sid, "-f", "markdown", "-o", str(out), "--force", "--project-dir", str(tmp_path)]
    )
    assert result.returncode == 0, result.output
    text = out.read_text(encoding="utf-8")
    assert f"Accepted by: {JANE}" in text
    assert "Recorded by: Sam Lee, ML Lead" in text


def test_json_export_still_validates_against_rmf_1_0_0(tmp_path: Path) -> None:
    """RMF schema 1.0.0 has no field for the names, so the JSON export leaves them out.

    PRD-338 adds them in RMF schema 1.1.0.
    """
    sid, rid = _init_and_assess(tmp_path)
    assert _mitigate(tmp_path, sid, rid, "--by", "Sam Lee, ML Lead").returncode == 0
    assert _accept(tmp_path, sid, rid, "--by", JANE).returncode == 0
    out = tmp_path / "rmf.json"
    result = run_rf(
        ["export", sid, "-f", "json", "-o", str(out), "--force", "--project-dir", str(tmp_path)]
    )
    assert result.returncode == 0, result.output
    rmf = json.loads(out.read_text(encoding="utf-8"))
    assert rmf["rmf_schema_version"] == "1.0.0"
    item = rmf["register"]["items"][0]
    assert "accepted_by" not in item
    assert all("recorded_by" not in m for m in item["mitigations"])
    assert run_rf(["verify", "--file", str(out)]).returncode == 0


# --- 1.1.3 registers ----------------------------------------------------------------


def test_v113_project_accepts_with_by_and_still_verifies(v113_project: tuple[Path, str]) -> None:
    root, sid = v113_project
    register = _register(root, sid)
    target = next(i for i in register["items"] if not i["accepted"])
    others = [i["id"] for i in register["items"] if i["id"] != target["id"]]
    result = _accept(root, sid, target["id"], "--by", JANE)
    assert result.returncode == 0, result.output
    assert run_rf(["verify", "--project-dir", str(root)]).returncode == 0
    after = {i["id"]: i for i in _register(root, sid)["items"]}
    assert after[target["id"]]["accepted_by"] == JANE
    for item_id in others:
        assert "accepted_by" not in after[item_id]
        assert all("recorded_by" not in m for m in after[item_id]["mitigations"])
