"""RiskForge 1.1.3 wrote tests/fixtures/v1_1_3_project. Every later version must still
verify its audit chain and its exported rmf.json (PRD-323).

These are characterisation tests: they pass on the 1.1.3 code by design."""

from __future__ import annotations

import hashlib
from pathlib import Path

from rf_testkit import run_rf

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "v1_1_3_project"


def test_fixture_files_are_unchanged() -> None:
    for line in (FIXTURE / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        actual = hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest()
        assert actual == digest, f"{name} changed; the 1.1.3 fixture must stay byte for byte"


def test_v113_chain_verifies(v113_project: tuple[Path, str]) -> None:
    root, _system_id = v113_project
    result = run_rf(["verify", "--project-dir", str(root)])
    assert result.returncode == 0, result.stdout + result.stderr


def test_v113_rmf_file_verifies(v113_project: tuple[Path, str]) -> None:
    root, _system_id = v113_project
    result = run_rf(["verify", "--file", str(root / "rmf.json")])
    assert result.returncode == 0, result.stdout + result.stderr
