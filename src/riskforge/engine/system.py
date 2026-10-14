"""SystemEngine: create and classify AI system records, each with its audit entry."""

from __future__ import annotations

from riskforge.engine.audit import AuditEngine
from riskforge.models.system import AISystem, AnnexIIICategory
from riskforge.storage.base import StorageBackend
from riskforge.storage.errors import RegisterNotFoundError


class SystemEngine:
    """Writes to ``system.yaml`` go through here, in one unit of work with their entry.

    Each change runs in ``AuditEngine.unit_of_work()``, so it raises ``IntegrityError``
    and changes nothing in a project that fails its integrity check.

    Register changes stay in :class:`~riskforge.engine.risk.RiskEngine`; ``classify``
    also updates the register's embedded copy of the system so the two never disagree.
    """

    def __init__(self, storage: StorageBackend, audit: AuditEngine) -> None:
        self._storage = storage
        self._audit = audit

    async def create(self, system: AISystem) -> AISystem:
        """Store a new system record and record ``system.created``."""
        system_id = str(system.id)
        async with self._audit.unit_of_work():
            await self._storage.write_system(system_id, system)
            self._audit.wrote_system(system_id)
            await self._audit.record(
                "system.created",
                system_id,
                {
                    "name": system.name,
                    "version": system.version,
                    "annex_iii_category": (
                        system.annex_iii_category.value if system.annex_iii_category else None
                    ),
                },
            )
        return system

    async def classify(self, system_id: str, category: AnnexIIICategory | None) -> AISystem:
        """Record the provider's Article 6(2) self-classification on the system and its register.

        Raises
        ------
        SystemNotFoundError
            If the project has no system with this id.
        """
        async with self._audit.unit_of_work():
            system = await self._audit.read_system(system_id)
            system.annex_iii_self_classification_documented = True
            if category is not None:
                system.annex_iii_category = category
            await self._storage.write_system(system_id, system)
            self._audit.wrote_system(system_id)
            try:
                register = await self._audit.read_register(system_id)
            except RegisterNotFoundError:
                register = None
            if register is not None:
                # validate reads the register's embedded system, not system.yaml.
                register.system.annex_iii_self_classification_documented = True
                if category is not None:
                    register.system.annex_iii_category = category
                await self._storage.write_register(system_id, register)
                self._audit.wrote_register(system_id)
            recorded = category or system.annex_iii_category
            await self._audit.record(
                "system.classified",
                system_id,
                {
                    "annex_iii_self_classification_documented": True,
                    "annex_iii_category": recorded.value if recorded else None,
                },
            )
        return system
