"""pytest-socket guards only the test process. CLI tests run riskforge in subprocesses,
which get tests/netblock/sitecustomize.py through rf_testkit.offline_env() (PRD-324)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
from rf_testkit import offline_env, run_rf

TESTS_DIR = Path(__file__).resolve().parents[1]
REENABLE_PATTERNS = ("enable_socket", "socket_enabled", "force-enable-socket")


def test_python_subprocesses_cannot_open_network_sockets() -> None:
    code = "import socket\nsocket.create_connection(('127.0.0.1', 9), timeout=1)\n"
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=offline_env(), timeout=60
    )
    assert result.returncode != 0
    assert "SocketBlockedError" in result.stderr


def test_cli_runs_with_the_network_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    # -X importtime lists every import attempt. It logs "sitecustomize" even when no such
    # module exists, so look for pytest_socket, which only the netblock guard imports.
    monkeypatch.setenv("PYTHONPROFILEIMPORTTIME", "1")
    result = run_rf(["--version"])
    assert result.returncode == 0, result.output
    assert "Zero telemetry" in result.output
    loaded = re.search(r"\|\s+pytest_socket$", result.stderr, re.MULTILINE)
    assert loaded, "the netblock guard was not loaded"
    # site.py only prints a failed sitecustomize import and carries on unguarded.
    assert "Error in sitecustomize" not in result.output


def test_no_test_reenables_sockets(request: pytest.FixtureRequest) -> None:
    assert request.config.getoption("--disable-socket"), "addopts must keep --disable-socket"
    assert not request.config.getoption("--force-enable-socket")
    this_file = Path(__file__).resolve()
    offenders = [
        str(path.relative_to(TESTS_DIR))
        for path in TESTS_DIR.rglob("*.py")
        if path.resolve() != this_file
        and any(p in path.read_text(encoding="utf-8") for p in REENABLE_PATTERNS)
    ]
    assert offenders == [], f"tests re-enabling sockets: {offenders}"
