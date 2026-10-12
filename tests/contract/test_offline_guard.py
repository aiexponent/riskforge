"""pytest-socket guards only the test process. CLI tests run riskforge in subprocesses,
which get tests/netblock/sitecustomize.py through rf_testkit.offline_env() (PRD-324)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from rf_testkit import offline_env, run_rf

TESTS_DIR = Path(__file__).resolve().parents[1]


def test_python_subprocesses_cannot_open_network_sockets() -> None:
    code = "import socket\nsocket.create_connection(('127.0.0.1', 9), timeout=1)\n"
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=offline_env(), timeout=60
    )
    assert result.returncode != 0
    assert "SocketBlockedError" in result.stderr


def test_cli_runs_with_the_network_blocked() -> None:
    result = run_rf(["--version"])
    assert result.returncode == 0, result.output
    assert "Zero telemetry" in result.output
    # site.py only prints a failed sitecustomize import and carries on unguarded.
    assert "Error in sitecustomize" not in result.output


def test_no_test_reenables_sockets() -> None:
    offenders = [
        str(path.relative_to(TESTS_DIR))
        for path in TESTS_DIR.rglob("test_*.py")
        if path.name != "test_offline_guard.py"
        and path.parent.name != "release"
        and "enable_socket" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"tests re-enabling sockets: {offenders}"
