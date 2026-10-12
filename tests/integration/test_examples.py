"""CI check: every example under examples/ must still match its golden RMF.

Runs scripts/eval.py, which drives each example through init, classify,
assess --answers, accept, and export, then diffs the normalised RMF against the
committed golden. Regenerate goldens after an intended change with `make eval-update`.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from rf_testkit import offline_env

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL = REPO_ROOT / "scripts" / "eval.py"


@pytest.mark.skipif(not EVAL.exists(), reason="run from a source checkout")
def test_examples_match_goldens() -> None:
    result = subprocess.run(
        [sys.executable, str(EVAL)],
        capture_output=True,
        text=True,
        env=offline_env(),
        timeout=240,
    )
    assert result.returncode == 0, (
        f"example evaluation failed or drifted:\n{result.stdout}\n{result.stderr}\n"
        "If the change was intended, run `make eval-update` and commit the updated goldens."
    )
