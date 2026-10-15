"""FileStore raises typed errors, each keeping the built-in base older callers catch."""

from __future__ import annotations

from pathlib import Path

import pytest
from riskforge.models.system import AISystem
from riskforge.storage.errors import (
    ManifestMissingError,
    ProjectExistsError,
    ProjectNotFoundError,
    RegisterNotFoundError,
    SystemNotFoundError,
)
from riskforge.storage.filesystem import FileStore


def test_errors_keep_builtin_bases() -> None:
    assert issubclass(ProjectNotFoundError, FileNotFoundError)
    assert issubclass(SystemNotFoundError, FileNotFoundError)
    assert issubclass(RegisterNotFoundError, FileNotFoundError)
    assert issubclass(ProjectExistsError, FileExistsError)
    assert issubclass(ManifestMissingError, ProjectNotFoundError)
    assert issubclass(ManifestMissingError, ProjectExistsError)


def test_ensure_project_without_manifest(tmp_path: Path) -> None:
    with pytest.raises(ProjectNotFoundError):
        FileStore(tmp_path).ensure_project()


async def test_second_init_raises_project_exists(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    await store.init_project("p", {})
    with pytest.raises(ProjectExistsError):
        await store.init_project("p", {})


async def test_init_without_manifest_but_with_a_system(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    await store.init_project("p", {})
    (tmp_path / ".riskforge" / "systems" / "s1").mkdir()
    (tmp_path / "riskforge.yaml").unlink()
    with pytest.raises(ManifestMissingError):
        store.ensure_project()
    with pytest.raises(ManifestMissingError):
        await store.init_project("q", {})
    assert not (tmp_path / "riskforge.yaml").exists()


async def test_unknown_system_and_missing_register(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    await store.init_project("p", {})
    with pytest.raises(SystemNotFoundError):
        await store.read_system("deadbeef")
    system = AISystem(name="S", version="1", purpose="p", provider_name="P")
    await store.write_system(str(system.id), system)
    with pytest.raises(RegisterNotFoundError):
        await store.read_register(str(system.id))
