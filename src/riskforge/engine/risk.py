"""RiskEngine — CRUD and scoring for risk items."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from riskforge.engine.audit import AuditEngine
from riskforge.models.register import RiskRegister
from riskforge.models.risk import Likelihood, Mitigation, RiskDimension, RiskItem, Severity
from riskforge.storage.base import StorageBackend
from riskforge.storage.errors import RegisterNotFoundError

VAGUE_PHRASES = {
    "we'll monitor it",
    "to be determined",
    "tbd",
    "n/a",
    "will address later",
    "monitor",
    "ongoing",
    "review",
}


class RiskNotFoundError(KeyError):
    pass


class AmbiguousRiskIdError(KeyError):
    """Raised when a risk id prefix matches more than one item."""


class RationaleRequiredError(ValueError):
    """Raised when a risk is accepted without a rationale."""


class RiskEngine:
    """CRUD and scoring for risk items.

    Every change reads the register, writes it and records its audit entry inside one
    ``unit_of_work()``, so concurrent writers cannot lose each other's updates and a
    write is never kept without its entry.
    """

    def __init__(self, storage: StorageBackend, audit: AuditEngine) -> None:
        self._storage = storage
        self._audit = audit

    async def create_register(
        self, system_id: str, assessor_name: str, assessor_role: str, review_months: int = 12
    ) -> tuple[RiskRegister, bool]:
        """Return the system's register, creating and recording one when there is none.

        The bool is True when this call created the register (event ``register.created``).

        Raises
        ------
        SystemNotFoundError
            If the project has no system with this id.
        """
        async with self._storage.unit_of_work():
            try:
                return await self._storage.read_register(system_id), False
            except RegisterNotFoundError:
                pass
            system = await self._storage.read_system(system_id)
            now = datetime.now(UTC)
            register = RiskRegister(
                system=system,
                assessor_name=assessor_name,
                assessor_role=assessor_role,
                assessment_date=now,
                review_date=now + timedelta(days=30 * review_months),
                question_bank_version="1.0.0",
            )
            await self._storage.write_register(system_id, register)
            await self._audit.record(
                "register.created",
                system_id,
                {
                    "assessor_name": assessor_name,
                    "assessor_role": assessor_role,
                    "review_date": register.review_date.isoformat(),
                },
            )
            return register, True

    async def add_risk(self, system_id: str, item: RiskItem) -> RiskItem:
        item.mitigations = [self._flag_vague(m) for m in item.mitigations]
        async with self._storage.unit_of_work():
            register = await self._storage.read_register(system_id)
            register.items.append(item)
            await self._storage.write_register(system_id, register)
            await self._audit.record(
                "risk_item.created",
                system_id,
                {
                    "risk_item_id": str(item.id),
                    "dimension": item.dimension,
                    "score": item.risk_score,
                },
            )
        return item

    async def update_risk(self, system_id: str, item: RiskItem) -> RiskItem:
        item.mitigations = [self._flag_vague(m) for m in item.mitigations]
        async with self._storage.unit_of_work():
            register = await self._storage.read_register(system_id)
            idx = next((i for i, r in enumerate(register.items) if r.id == item.id), None)
            if idx is None:
                raise RiskNotFoundError(str(item.id))
            old_score = register.items[idx].risk_score
            register.items[idx] = item
            await self._storage.write_register(system_id, register)
            await self._audit.record(
                "risk_item.updated",
                system_id,
                {
                    "risk_item_id": str(item.id),
                    "old_score": old_score,
                    "new_score": item.risk_score,
                },
            )
        return item

    async def accept_risk(
        self, system_id: str, risk_id: str, rationale: str, actor_identity: str
    ) -> RiskItem:
        if not rationale.strip():
            raise RationaleRequiredError("Acceptance rationale is required and cannot be empty.")
        async with self._storage.unit_of_work():
            register = await self._storage.read_register(system_id)
            item = self._resolve_risk_item(register.items, risk_id)
            risk_id = str(item.id)
            old_accepted = item.accepted
            item.accepted = True
            item.acceptance_rationale = rationale
            await self._storage.write_register(system_id, register)
            await self._audit.record(
                "risk.accepted",
                system_id,
                {
                    "risk_item_id": risk_id,
                    "old_accepted": old_accepted,
                    "rationale_hash": self._hash_rationale(rationale),
                    "actor": actor_identity,
                },
            )
        return item

    async def add_mitigation(
        self,
        system_id: str,
        risk_id: str,
        mitigation: Mitigation,
        residual_likelihood: int | None = None,
        residual_severity: int | None = None,
    ) -> RiskItem:
        """Append a mitigation to a risk item and optionally re-score residual risk."""
        async with self._storage.unit_of_work():
            register = await self._storage.read_register(system_id)
            item = self._resolve_risk_item(register.items, risk_id)
            item.mitigations.append(self._flag_vague(mitigation))
            if residual_likelihood is not None:
                item.residual_likelihood = Likelihood(residual_likelihood)
            if residual_severity is not None:
                item.residual_severity = Severity(residual_severity)
            await self._storage.write_register(system_id, register)
            await self._audit.record(
                "mitigation.added",
                system_id,
                {
                    "risk_item_id": str(item.id),
                    "control_type": mitigation.control_type,
                    "is_vague": mitigation.is_vague,
                },
            )
        return item

    async def list_risks(
        self, system_id: str, dimension: RiskDimension | None = None
    ) -> list[RiskItem]:
        register = await self._storage.read_register(system_id)
        if dimension is not None:
            return [i for i in register.items if i.dimension == dimension]
        return register.items

    @staticmethod
    def _flag_vague(mitigation: Mitigation) -> Mitigation:
        mitigation.is_vague = any(
            phrase in mitigation.description.lower() for phrase in VAGUE_PHRASES
        )
        return mitigation

    @staticmethod
    def _hash_rationale(rationale: str) -> str:
        return hashlib.sha256(rationale.encode()).hexdigest()[:16]

    @staticmethod
    def _resolve_risk_item(items: list[RiskItem], risk_id: str) -> RiskItem:
        """Resolve a full or prefix risk id to a single item.

        `risk list` prints the first 8 characters of each id, so users pass a
        prefix. Accept an exact match first, then a unique prefix match. Raise a
        clear error when nothing matches or the prefix is ambiguous.
        """
        exact = [i for i in items if str(i.id) == risk_id]
        if len(exact) == 1:
            return exact[0]
        matches = [i for i in items if str(i.id).startswith(risk_id)]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise RiskNotFoundError(risk_id)
        raise AmbiguousRiskIdError(
            f"'{risk_id}' matches {len(matches)} risk items; use more characters of the id."
        )
