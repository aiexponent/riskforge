"""validate --force (D11 of the 2.0.0 independent test).

The help said "Export even if FAIL gates present", but validate never exports: --force
only changes its exit code.
"""

from __future__ import annotations

from rf_testkit import run_rf


def test_validate_force_help_says_it_does_not_export() -> None:
    result = run_rf(["validate", "--help"])
    assert result.returncode == 0, result.output
    text = " ".join(result.output.split())
    assert "Export even if" not in text
    assert "validate never exports" in text
    assert "export --force" in text
