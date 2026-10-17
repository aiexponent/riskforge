"""Shared pytest fixtures for RiskForge test suite."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
import yaml
from rf_testkit import RELEASE_ENV


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_system_yaml(fixtures_dir: Path) -> Path:
    return fixtures_dir / "systems" / "sample_system.yaml"


V113_DIR = Path(__file__).parent / "fixtures" / "v1_1_3_project"


def materialise_v113(dest: Path) -> tuple[Path, str]:
    """Rebuild the 1.1.3 fixture's on-disk layout under ``dest``; return (project_dir, system_id)."""
    system_id = yaml.safe_load((V113_DIR / "system.yaml").read_text(encoding="utf-8"))["id"]
    system_dir = dest / ".riskforge" / "systems" / system_id
    system_dir.mkdir(parents=True)
    shutil.copyfile(V113_DIR / "manifest.yaml", dest / "riskforge.yaml")
    shutil.copyfile(V113_DIR / "audit.jsonl", dest / ".riskforge" / "audit.jsonl")
    for name in ("system.yaml", "register.yaml", "mitigations.yaml"):
        shutil.copyfile(V113_DIR / name, system_dir / name)
    shutil.copyfile(V113_DIR / "rmf.json", dest / "rmf.json")
    return dest, system_id


@pytest.fixture
def v113_project(tmp_path: Path) -> tuple[Path, str]:
    return materialise_v113(tmp_path / "v113")


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """With RISKFORGE_RELEASE_CHECK set, a run that selects no release test is an error.

    Runs after the -m deselection, so a release workflow step whose command drops
    `-m release` or `tests/release` fails instead of passing without the check.
    """
    if os.environ.get(RELEASE_ENV) and not any(i.get_closest_marker("release") for i in items):
        raise pytest.UsageError(
            f"{RELEASE_ENV} is set but no release test is selected: "
            "run pytest -m release tests/release"
        )
