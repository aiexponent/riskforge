"""run_rf() output must not depend on the CI environment the suite runs in."""

from __future__ import annotations

import pytest
from rf_testkit import run_rf


@pytest.mark.parametrize("var", ["GITHUB_ACTIONS", "FORCE_COLOR", "PY_COLORS"])
def test_cli_output_has_no_ansi_codes_when_ci_forces_a_terminal(
    monkeypatch: pytest.MonkeyPatch, var: str
) -> None:
    # Typer forces a rich terminal when any of these is set, so option names in a usage
    # error come back wrapped in bold escape codes and substring checks stop matching.
    monkeypatch.setenv(var, "true")
    result = run_rf(["risk", "mitigate", "x", "y", "--residual-likelihood", "7"])
    assert result.returncode == 3, result.output
    assert "\x1b[" not in result.output, result.output
    assert "--residual-likelihood" in result.output, result.output
