"""The storage contract fails a backend that gets each property wrong.

Every class here is a FileStore, or a FileStore contract, broken in one way. Each test runs
the contract test that must catch that fault and requires it to fail, so CI keeps proving
the suite can fail and not only that FileStore passes it.
"""

from __future__ import annotations

import contextlib
import os
import unicodedata
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
from riskforge.api import (
    AISystem,
    FileStore,
    RiskRegister,
    StorageBackend,
    check_integrity,
)
from riskforge.storage.base import WRITTEN_STATE_KEY
from riskforge.storage.filesystem import _pending

import contract.test_filestore_contract as filestore_contract

# Failures a contract test can end in: an assertion, or an error the broken backend raises.
CONTRACT_FAILURES = (AssertionError, RuntimeError, OSError, ValueError)


class _FileStoreContract(filestore_contract.TestFileStoreContract):
    """The FileStore hooks, with the store class a subclass picks. Not collected."""

    __test__ = False
    store_class: type[FileStore] = FileStore

    async def make_storage(self, tmp_path: Path, system_id: str) -> StorageBackend:
        self.project_dir = tmp_path / "project"
        store = self.store_class(self.project_dir)
        await store.init_project("contract", {"created_by": "storage contract"})
        return store

    async def make_second_handle(self, storage: StorageBackend) -> StorageBackend:
        return self.store_class(self.project_dir)


# --- broken backends --------------------------------------------------------------------


class _TrustingChainStore(FileStore):
    """Says the audit chain is intact without checking it."""

    async def verify_chain(self) -> tuple[bool, list[str]]:
        return True, []


class _HeadFromLastRowStore(FileStore):
    """Reports the last row of the log as the head instead of storing the head separately."""

    async def read_audit_head(self) -> dict | None:
        last = await self.read_last_audit_entry()
        return None if last is None else {"seq": last.seq, "entry_hash": last.entry_hash}


class _CommitsOnCleanExitStore(FileStore):
    """Discards unrecorded writes after an error, but commits them when the scope ends cleanly."""

    @contextlib.asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[None]:
        outermost = self._scope() is None
        async with super().unit_of_work():
            yield
            scope = self._scope()
            if outermost and scope is not None:
                for relative in list(scope.staged):
                    path = self._root / relative
                    os.replace(_pending(path), path)
                scope.staged.clear()
                scope.state.pop(WRITTEN_STATE_KEY, None)


class _LocksPerObjectStore(FileStore):
    """Locks each FileStore object on its own, so two handles on one project do not exclude."""

    def __init__(self, project_dir: Path, *args: Any, **kwargs: Any) -> None:
        super().__init__(project_dir, *args, **kwargs)
        self._lock_path = self._root / f"audit.{id(self)}.lock"
        self._key = f"{self._key}#{id(self)}"


def _mangling(mangle: Callable[[str], str]) -> type[FileStore]:
    """A FileStore that passes every stored string of a system or register through ``mangle``."""

    def walk(value: Any) -> Any:
        if isinstance(value, str):
            return mangle(value)
        if isinstance(value, dict):
            return {key: walk(inner) for key, inner in value.items()}
        if isinstance(value, list):
            return [walk(inner) for inner in value]
        return value

    class _ManglingStore(FileStore):
        async def write_system(self, system_id: str, data: AISystem) -> None:
            mangled = AISystem.model_validate(walk(data.model_dump(mode="json")))
            await super().write_system(system_id, mangled)

        async def write_register(self, system_id: str, register: RiskRegister) -> None:
            mangled = RiskRegister.model_validate(walk(register.model_dump(mode="json")))
            await super().write_register(system_id, mangled)

    return _ManglingStore


# --- the contract test that catches each fault -------------------------------------------


async def test_a_backend_that_trusts_its_own_chain_check_is_still_caught(
    tmp_path: Path,
) -> None:
    # check_integrity recomputes the chain itself, so an audit edit fails the check even
    # when the backend's verify_chain always reports it intact.
    contract = _FileStoreContract()
    contract.store_class = _TrustingChainStore
    await contract.test_an_audit_entry_changed_outside_riskforge_fails_the_check(tmp_path)


async def test_a_tamper_audit_hook_that_empties_the_log_fails(tmp_path: Path) -> None:
    class Contract(_FileStoreContract):
        async def tamper_audit(self, storage: StorageBackend) -> None:
            (self.project_dir / ".riskforge" / "audit.jsonl").write_text("", encoding="utf-8")

    with pytest.raises(AssertionError):
        await Contract().test_an_audit_entry_changed_outside_riskforge_fails_the_check(tmp_path)


async def test_a_tamper_audit_hook_that_edits_the_wrong_entry_fails(tmp_path: Path) -> None:
    class Contract(_FileStoreContract):
        async def tamper_audit(self, storage: StorageBackend) -> None:
            path = self.project_dir / ".riskforge" / "audit.jsonl"
            lines = path.read_text(encoding="utf-8").splitlines()
            lines[-1] = lines[-1].replace('"payload":{', '"payload":{"tampered":true,', 1)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(AssertionError):
        await Contract().test_an_audit_entry_changed_outside_riskforge_fails_the_check(tmp_path)


async def test_a_tamper_register_hook_that_changes_nothing_fails(tmp_path: Path) -> None:
    class Contract(_FileStoreContract):
        async def tamper_register(self, storage: StorageBackend, system_id: str) -> None:
            return None

    with pytest.raises(AssertionError):
        await Contract().test_a_register_changed_outside_riskforge_fails_the_check(tmp_path)


async def test_a_head_read_from_the_last_row_fails(tmp_path: Path) -> None:
    contract = _FileStoreContract()
    contract.store_class = _HeadFromLastRowStore
    with pytest.raises(AssertionError, match="removed from the end"):
        await contract.test_an_audit_entry_removed_from_the_end_fails_the_check(tmp_path)


async def test_a_drop_hook_that_removes_nothing_fails(tmp_path: Path) -> None:
    class Contract(_FileStoreContract):
        async def drop_last_audit_entry(self, storage: StorageBackend) -> None:
            return None

    with pytest.raises(AssertionError):
        await Contract().test_an_audit_entry_removed_from_the_end_fails_the_check(tmp_path)


async def test_a_backend_that_commits_unrecorded_writes_on_a_clean_exit_fails(
    tmp_path: Path,
) -> None:
    contract = _FileStoreContract()
    contract.store_class = _CommitsOnCleanExitStore
    # The same backend still discards them when the scope ends with an error.
    await contract.test_a_change_without_an_entry_is_discarded(tmp_path / "error")
    with pytest.raises(AssertionError):
        await contract.test_a_change_without_an_entry_is_discarded_on_a_clean_exit(
            tmp_path / "clean"
        )


async def test_a_backend_that_locks_each_object_on_its_own_fails_with_two_handles(
    tmp_path: Path,
) -> None:
    contract = _FileStoreContract()
    contract.store_class = _LocksPerObjectStore
    # One handle serialises its own writers, so only the two-handle test catches it.
    await contract.test_concurrent_writers_lose_no_update(tmp_path / "one")
    with pytest.raises(CONTRACT_FAILURES):
        await contract.test_concurrent_writers_on_two_handles_lose_no_update(tmp_path / "two")


@pytest.mark.parametrize(
    "mangle",
    [
        pytest.param(lambda text: unicodedata.normalize("NFC", text), id="NFC normalisation"),
        pytest.param(lambda text: text.replace("\r\n", "\n"), id="CRLF to LF"),
        pytest.param(lambda text: text.removesuffix("\n"), id="trailing line break dropped"),
    ],
)
async def test_a_backend_that_changes_text_fails(
    mangle: Callable[[str], str], tmp_path: Path
) -> None:
    contract = _FileStoreContract()
    contract.store_class = _mangling(mangle)
    with pytest.raises(AssertionError):
        await contract.test_awkward_text_reads_back_exactly_and_verifies(tmp_path)


async def test_the_broken_stores_still_pass_check_integrity_when_untouched(
    tmp_path: Path,
) -> None:
    # So each test above fails for its fault, not because the broken store is unusable.
    for n, store_class in enumerate(
        [_TrustingChainStore, _HeadFromLastRowStore, _CommitsOnCleanExitStore, _LocksPerObjectStore]
    ):
        contract = _FileStoreContract()
        contract.store_class = store_class
        storage, _audit, _system_id = await contract._seeded(tmp_path / str(n))
        assert (await check_integrity(storage)).ok
