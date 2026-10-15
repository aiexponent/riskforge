"""CLI behaviour when the project lock is held or the audit log is corrupt (PRD-331)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from filelock import FileLock
from rf_testkit import offline_env, run_rf

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

# The real console entry point, with a short lock wait so the test does not sit for 120 s.
SHORT_WAIT_CLI = (
    "import sys\n"
    "import riskforge.storage.filesystem as filesystem\n"
    "filesystem.DEFAULT_LOCK_TIMEOUT = 0.5\n"
    "from riskforge.cli.main import run\n"
    "sys.argv = ['riskforge', *sys.argv[1:]]\n"
    "run()\n"
)


def _init(project: Path) -> str:
    result = run_rf(
        ["init", "-n", "S", "-s", "1", "-p", "p", "--provider", "P", "--project-dir", str(project)]
    )
    assert result.returncode == 0, result.output
    return UUID_RE.search(result.output).group(0)


def test_a_held_project_lock_is_one_line_and_exit_1(tmp_path: Path) -> None:
    sid = _init(tmp_path)
    holder = FileLock(str(tmp_path / ".riskforge" / "audit.lock"))
    holder.acquire()
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                SHORT_WAIT_CLI,
                "system",
                "classify",
                sid,
                "--confirm",
                "--project-dir",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            env=offline_env(),
            stdin=subprocess.DEVNULL,
            timeout=180,
        )
    finally:
        holder.release()
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "Another riskforge process" in output
    assert "Traceback" not in output
    assert len(output.strip().splitlines()) == 1, output


def test_a_corrupt_audit_log_stops_a_change_with_exit_2(tmp_path: Path) -> None:
    sid = _init(tmp_path)
    with (tmp_path / ".riskforge" / "audit.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    result = run_rf(["system", "classify", sid, "--confirm", "--project-dir", str(tmp_path)])
    assert result.returncode == 2, result.output
    assert "Traceback" not in result.output
    lines = result.output.strip().splitlines()
    # One line per finding between the header and the closing hint (PRD-333).
    assert lines[0].startswith("✗ Integrity check failed"), result.output
    assert all(line.startswith("  • ") for line in lines[1:-1]), result.output
    assert any("Line 2: not valid JSON" in line for line in lines[1:-1]), result.output
    assert result.output.count("riskforge verify") == 1, result.output


def test_an_unexplained_log_after_an_interrupted_commit_is_one_line_exit_2(
    tmp_path: Path,
) -> None:
    import json

    sid = _init(tmp_path)
    root = tmp_path / ".riskforge"
    log = root / "audit.jsonl"
    first = log.read_text().splitlines()[0]
    (root / "txn.json").write_text(
        json.dumps({"after_seq": 0, "log_size": log.stat().st_size, "files": []})
    )
    with log.open("a", encoding="utf-8") as fh:
        fh.write(first + "\n" + first + "\n")
    result = run_rf(["system", "classify", sid, "--confirm", "--project-dir", str(tmp_path)])
    assert result.returncode == 2, result.output
    assert "Traceback" not in result.output
    assert len(result.output.strip().splitlines()) == 1, result.output
    assert result.output.count("riskforge verify") == 1, result.output
