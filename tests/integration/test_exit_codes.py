"""Exit codes: 0 ok, 1 gate failure, 2 integrity failure, 3 usage or input error."""

from __future__ import annotations

import subprocess
import sys

from rf_testkit import offline_env, run_rf


def test_unknown_option_exits_3() -> None:
    result = run_rf(["verify", "--bogus"])
    assert result.returncode == 3, result.output
    assert "No such option" in result.output


def test_missing_required_option_exits_3() -> None:
    assert run_rf(["init"]).returncode == 3


def test_unknown_command_exits_3() -> None:
    assert run_rf(["verifyy"]).returncode == 3


def test_no_arguments_prints_help_and_exits_0() -> None:
    result = run_rf([])
    assert result.returncode == 0
    assert "Usage" in result.output


def test_python_dash_m_follows_the_same_contract() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "riskforge", "verify", "--bogus"],
        capture_output=True,
        text=True,
        env=offline_env(),
        stdin=subprocess.DEVNULL,
        timeout=60,
    )
    assert result.returncode == 3
