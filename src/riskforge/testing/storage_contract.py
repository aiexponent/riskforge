"""The behaviour every StorageBackend must have.

Subclass StorageContract in a test module under a name that starts with ``Test`` and
implement the three hooks. Each test builds its own storage for one AI system and drives it
through the RiskForge engines and ``check_integrity``, the same calls the CLI and the server
make.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

try:
    import pytest
except ImportError as exc:  # pragma: no cover - only without the testing extra
    raise ImportError('riskforge.testing needs pytest: pip install "riskforge[testing]"') from exc

from riskforge.api import (
    AISystem,
    AuditActor,
    AuditEngine,
    Likelihood,
    Mitigation,
    RegisterNotFoundError,
    RiskDimension,
    RiskEngine,
    RiskItem,
    Severity,
    StorageBackend,
    SystemEngine,
    SystemNotFoundError,
    check_integrity,
    document_fingerprint,
)

# Text that YAML or JSON storage can easily get wrong: non-ASCII, line breaks, and
# strings a YAML reader would otherwise turn into a bool, null, number, comment or list.
AWKWARD_TEXT = [
    "Müller GmbH",
    "line one\nline two: with a colon",
    "yes",
    "null",
    "1.0",
    "  leading and trailing  ",
    'it\'s "quoted"',
    "#not a comment",
    "- not a list",
    "key: value",
]

ACTOR = AuditActor(type="api", identity="storage-contract")


def _item(title: str, dimension: RiskDimension = RiskDimension.privacy) -> RiskItem:
    return RiskItem(
        dimension=dimension,
        title=title,
        description=title,
        likelihood=Likelihood(2),
        severity=Severity(3),
        residual_likelihood=Likelihood(2),
        residual_severity=Severity(3),
    )


def _system() -> AISystem:
    return AISystem(
        name="Contract System", version="1", purpose="storage contract", provider_name="P"
    )


@pytest.mark.asyncio
class StorageContract:
    """Behaviour every StorageBackend must have. Subclass it and implement the hooks."""

    async def make_storage(self, tmp_path: Path, system_id: str) -> StorageBackend:
        """Return an empty, ready store that will hold the AI system ``system_id``."""
        raise NotImplementedError("StorageContract subclasses must implement make_storage")

    async def tamper_register(self, storage: StorageBackend, system_id: str) -> None:
        """Change the stored register of ``system_id`` without going through RiskForge."""
        raise NotImplementedError("StorageContract subclasses must implement tamper_register")

    async def tamper_audit(self, storage: StorageBackend) -> None:
        """Change the payload of the second stored audit entry without going through RiskForge."""
        raise NotImplementedError("StorageContract subclasses must implement tamper_audit")

    async def _seeded(
        self, tmp_path: Path, system: AISystem | None = None
    ) -> tuple[StorageBackend, AuditEngine, str]:
        system = system or _system()
        system_id = str(system.id)
        storage = await self.make_storage(tmp_path, system_id)
        audit = AuditEngine(storage, ACTOR)
        await SystemEngine(storage, audit).create(system)
        await RiskEngine(storage, audit).create_register(system_id, "Assessor", "Role")
        return storage, audit, system_id

    async def test_a_change_and_its_entry_are_visible_together(self, tmp_path: Path) -> None:
        storage, audit, system_id = await self._seeded(tmp_path)
        before = [entry async for entry in storage.read_audit()]
        await RiskEngine(storage, audit).add_risk(system_id, _item("one"))
        after = [entry async for entry in storage.read_audit()]
        assert [entry.event for entry in after[len(before) :]] == ["risk_item.created"]
        assert [item.title for item in (await storage.read_register(system_id)).items] == ["one"]
        assert (await check_integrity(storage)).ok

    async def test_a_change_without_an_entry_is_discarded(self, tmp_path: Path) -> None:
        storage, audit, system_id = await self._seeded(tmp_path)
        before = [entry async for entry in storage.read_audit()]
        register = await storage.read_register(system_id)
        register.items.append(_item("never recorded"))
        with pytest.raises(RuntimeError, match="stop before recording"):
            async with audit.unit_of_work():
                await storage.write_register(system_id, register)
                audit.wrote_register(system_id)
                raise RuntimeError("stop before recording")
        assert (await storage.read_register(system_id)).items == []
        assert [entry async for entry in storage.read_audit()] == before
        assert (await check_integrity(storage)).ok

    async def test_an_append_outside_a_unit_of_work_is_refused(self, tmp_path: Path) -> None:
        storage, _audit, _system_id = await self._seeded(tmp_path)
        last = await storage.read_last_audit_entry()
        assert last is not None
        with pytest.raises(RuntimeError, match="unit_of_work"):
            await storage.append_audit(last)

    async def test_reads_inside_a_unit_of_work_see_its_own_writes(self, tmp_path: Path) -> None:
        storage, audit, system_id = await self._seeded(tmp_path)
        async with audit.unit_of_work():
            register = await storage.read_register(system_id)
            register.items.append(_item("staged"))
            await storage.write_register(system_id, register)
            audit.wrote_register(system_id)
            staged = await storage.read_register(system_id)
            assert [item.title for item in staged.items] == ["staged"]
            await audit.record("risk_item.created", system_id, {"title": "staged"})
        assert [item.title for item in (await storage.read_register(system_id)).items] == ["staged"]
        assert (await check_integrity(storage)).ok

    async def test_nested_units_of_work_join_the_outer_one(self, tmp_path: Path) -> None:
        storage, audit, system_id = await self._seeded(tmp_path)
        async with audit.unit_of_work():
            async with storage.unit_of_work():
                register = await storage.read_register(system_id)
                register.items.append(_item("nested"))
                await storage.write_register(system_id, register)
                audit.wrote_register(system_id)
            await audit.record("risk_item.created", system_id, {"title": "nested"})
        assert [item.title for item in (await storage.read_register(system_id)).items] == ["nested"]
        assert (await check_integrity(storage)).ok

    async def test_concurrent_writers_lose_no_update(self, tmp_path: Path) -> None:
        # Twenty writers on one event loop. Writers in separate processes are a
        # property of each backend's locking and are tested with the backend.
        storage, audit, system_id = await self._seeded(tmp_path)
        engine = RiskEngine(storage, audit)
        await asyncio.gather(*(engine.add_risk(system_id, _item(f"writer {n}")) for n in range(20)))
        titles = sorted(item.title for item in (await storage.read_register(system_id)).items)
        assert titles == sorted(f"writer {n}" for n in range(20))
        entries = [entry async for entry in storage.read_audit()]
        assert len([entry for entry in entries if entry.event == "risk_item.created"]) == 20
        assert [entry.seq for entry in entries] == list(range(22))
        assert (await check_integrity(storage)).ok

    async def test_awkward_text_reads_back_exactly_and_verifies(self, tmp_path: Path) -> None:
        system = AISystem(
            name=AWKWARD_TEXT[0],
            version="null",
            purpose=AWKWARD_TEXT[1],
            provider_name=AWKWARD_TEXT[0],
            deployment_context="yes",
        )
        storage, audit, system_id = await self._seeded(tmp_path, system)
        engine = RiskEngine(storage, audit)
        for text in AWKWARD_TEXT:
            item = _item(text)
            item.mitigations = [
                Mitigation(
                    description=text, control_type="preventive", owner=text, status="planned"
                )
            ]
            await engine.add_risk(system_id, item)
        assert await storage.read_system(system_id) == system
        register = await storage.read_register(system_id)
        assert register.system == system
        assert [item.title for item in register.items] == AWKWARD_TEXT
        assert [item.description for item in register.items] == AWKWARD_TEXT
        assert [item.mitigations[0].description for item in register.items] == AWKWARD_TEXT
        assert [item.mitigations[0].owner for item in register.items] == AWKWARD_TEXT
        document = await storage.read_register_document(system_id)
        assert document == register.model_dump(mode="json")
        last = await storage.read_last_audit_entry()
        assert last is not None
        assert document_fingerprint(document) == last.register_fingerprint
        assert document_fingerprint(await storage.read_register_document(system_id)) == (
            last.register_fingerprint
        )
        assert (await check_integrity(storage)).ok

    async def test_unknown_system_and_missing_register_raise_typed_errors(
        self, tmp_path: Path
    ) -> None:
        system = AISystem(name="Unregistered", version="1", purpose="p", provider_name="P")
        system_id = str(system.id)
        storage = await self.make_storage(tmp_path, system_id)
        with pytest.raises(SystemNotFoundError):
            await storage.read_system(system_id)
        await SystemEngine(storage, AuditEngine(storage, ACTOR)).create(system)
        with pytest.raises(RegisterNotFoundError):
            await storage.read_register(system_id)
        with pytest.raises(RegisterNotFoundError):
            await storage.read_register_document(system_id)

    async def test_read_audit_filters_by_system_and_position(self, tmp_path: Path) -> None:
        storage, audit, system_id = await self._seeded(tmp_path)
        await RiskEngine(storage, audit).add_risk(system_id, _item("one"))
        entries = [entry async for entry in storage.read_audit(system_id=system_id)]
        assert [entry.event for entry in entries] == [
            "system.created",
            "register.created",
            "risk_item.created",
        ]
        assert [entry async for entry in storage.read_audit(system_id="another system")] == []
        later = [entry async for entry in storage.read_audit(since_seq=entries[1].seq)]
        assert [entry.seq for entry in later] == [entries[1].seq, entries[2].seq]
        last = await storage.read_last_audit_entry()
        assert last is not None
        assert last.entry_hash == entries[-1].entry_hash
        assert await storage.list_systems() == [system_id]

    async def test_a_register_changed_outside_riskforge_fails_the_check(
        self, tmp_path: Path
    ) -> None:
        storage, audit, system_id = await self._seeded(tmp_path)
        await RiskEngine(storage, audit).add_risk(system_id, _item("one"))
        await self.tamper_register(storage, system_id)
        report = await check_integrity(storage)
        assert not report.ok
        assert any("changed outside RiskForge" in error for error in report.errors)

    async def test_an_audit_entry_changed_outside_riskforge_fails_the_check(
        self, tmp_path: Path
    ) -> None:
        storage, audit, system_id = await self._seeded(tmp_path)
        await RiskEngine(storage, audit).add_risk(system_id, _item("one"))
        await self.tamper_audit(storage)
        assert not (await check_integrity(storage)).ok
