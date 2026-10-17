"""FileStore passes the storage contract that every RiskForge backend must pass."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import riskforge.api
import riskforge.testing
import yaml
from rf_testkit import offline_env
from riskforge.api import FileStore, StorageBackend
from riskforge.testing import StorageContract


class TestFileStoreContract(StorageContract):
    async def make_storage(self, tmp_path: Path, system_id: str) -> StorageBackend:
        self.project_dir = tmp_path / "project"
        store = FileStore(self.project_dir)
        await store.init_project("contract", {"created_by": "storage contract"})
        return store

    async def tamper_register(self, storage: StorageBackend, system_id: str) -> None:
        path = self.project_dir / ".riskforge" / "systems" / system_id / "register.yaml"
        register = yaml.safe_load(path.read_text(encoding="utf-8"))
        register["items"][0]["title"] = "Edited outside RiskForge"
        path.write_text(
            yaml.safe_dump(register, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )

    async def tamper_audit(self, storage: StorageBackend) -> None:
        path = self.project_dir / ".riskforge" / "audit.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        entry = json.loads(lines[1])
        entry["payload"]["tampered"] = True
        lines[1] = json.dumps(entry, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    async def drop_last_audit_entry(self, storage: StorageBackend) -> None:
        path = self.project_dir / ".riskforge" / "audit.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        path.write_text("".join(lines[:-1]), encoding="utf-8")

    async def make_second_handle(self, storage: StorageBackend) -> StorageBackend:
        return FileStore(self.project_dir)


@pytest.mark.parametrize(
    "hook", ["make_storage", "tamper_register", "tamper_audit", "drop_last_audit_entry"]
)
async def test_a_backend_that_skips_a_hook_fails_loudly(hook: str, tmp_path: Path) -> None:
    contract = StorageContract()
    arguments = {
        "make_storage": (tmp_path, "system"),
        "tamper_register": (None, "system"),
        "tamper_audit": (None,),
        "drop_last_audit_entry": (None,),
    }[hook]
    with pytest.raises(NotImplementedError, match=hook):
        await getattr(contract, hook)(*arguments)


async def test_a_backend_without_a_second_handle_skips_both_checks_and_says_why() -> None:
    with pytest.raises(
        pytest.skip.Exception,
        match=(
            r"make_second_handle is not implemented, so both second-handle checks were "
            r"skipped: writers on two handles of one store, and a head kept per handle"
        ),
    ):
        await StorageContract().make_second_handle(None)


def test_the_contract_is_its_own_module_outside_the_api() -> None:
    assert riskforge.testing.__all__ == ["StorageContract"]
    assert "StorageContract" not in riskforge.api.__all__


@pytest.mark.parametrize("missing", ["pytest", "pytest_asyncio"])
def test_the_contract_without_the_testing_extra_says_what_to_install(missing: str) -> None:
    code = (
        "import sys\n"
        f"sys.modules[{missing!r}] = None\n"
        "try:\n"
        "    import riskforge.testing\n"
        "except ImportError as exc:\n"
        "    print(exc)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        env=offline_env(),
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        'riskforge.testing needs pytest and pytest-asyncio: pip install "riskforge[testing]"'
    )


def test_importing_the_contract_loads_neither_the_cli_nor_weasyprint() -> None:
    code = (
        "import sys, riskforge.testing\n"
        "print(sorted(m for m in ('typer', 'weasyprint', 'riskforge.cli') if m in sys.modules))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        env=offline_env(),
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"
