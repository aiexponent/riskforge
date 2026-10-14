"""FileStore stays usable on native Windows, which CI does not run.

Windows cannot open a directory with ``os.open``, and opens file descriptors in text
mode unless ``O_BINARY`` is passed, which would turn every ``\\n`` the audit log
writes into ``\\r\\n``. Both are simulated here on POSIX.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from riskforge.engine.audit import AuditEngine
from riskforge.engine.system import SystemEngine
from riskforge.models.audit import AuditActor
from riskforge.models.system import AISystem
from riskforge.storage import filesystem
from riskforge.storage.filesystem import FileStore

WINDOWS_O_BINARY = 0x8000
ACTOR = AuditActor(type="human", identity="tester")


def _create_project(root: Path) -> None:
    async def body() -> None:
        store = FileStore(root)
        await store.init_project("p", {"name": "p"})
        await SystemEngine(store, AuditEngine(store, ACTOR)).create(
            AISystem(name="Scoring", version="1.0", purpose="Scoring", provider_name="Acme")
        )

    asyncio.run(body())


def test_directory_fsync_is_skipped_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_open = os.open

    def windows_open(path, flags, *args, **kwargs):  # noqa: ANN001, ANN202
        if Path(path).is_dir():
            raise PermissionError(13, "Permission denied", str(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(filesystem, "_IS_WINDOWS", True, raising=False)
    monkeypatch.setattr(filesystem.os, "open", windows_open)
    _create_project(tmp_path)
    assert (tmp_path / ".riskforge" / "audit.jsonl").read_bytes().count(b"\n") == 1


def test_stored_files_are_opened_in_binary_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_open = os.open
    file_flags: list[tuple[str, int]] = []

    def recording_open(path, flags, *args, **kwargs):  # noqa: ANN001, ANN202
        name = Path(path).name
        # The lock file is filelock's and temporary files are tempfile's (binary on Windows).
        if not Path(path).is_dir() and name != "audit.lock" and not name.endswith(".tmp"):
            file_flags.append((name, flags))
        return real_open(path, flags & ~WINDOWS_O_BINARY, *args, **kwargs)

    monkeypatch.setattr(filesystem, "_O_BINARY", WINDOWS_O_BINARY, raising=False)
    monkeypatch.setattr(filesystem.os, "open", recording_open)
    _create_project(tmp_path)
    asyncio.run(FileStore(tmp_path).read_audit_head())

    names = {name for name, _flags in file_flags}
    assert {"riskforge.yaml", "audit.jsonl", "audit.head.json"} <= names
    assert all(flags & WINDOWS_O_BINARY for _name, flags in file_flags), file_flags
