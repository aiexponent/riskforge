"""RiskEngine — CRUD and scoring for risk items."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Literal, NamedTuple

from riskforge.engine.actor import require_actor_name
from riskforge.engine.audit import AuditEngine
from riskforge.models.register import RiskRegister
from riskforge.models.requirements import TestRequirement
from riskforge.models.risk import (
    Likelihood,
    Mitigation,
    RiskDimension,
    RiskItem,
    Severity,
    is_vague_description,
)
from riskforge.storage.base import StorageBackend
from riskforge.storage.errors import RegisterNotFoundError


class RiskNotFoundError(KeyError):
    pass


class AmbiguousRiskIdError(KeyError):
    """Raised when a risk id prefix matches more than one item."""


class RationaleRequiredError(ValueError):
    """Raised when a risk is accepted without a rationale."""


UpsertOutcome = Literal["added", "updated", "unchanged"]


class UpsertResult(NamedTuple):
    """What ``RiskEngine.upsert_item`` did.

    ``item`` is the stored item, ``previous`` a copy of it before an update (None when
    added), and ``matches`` how many register items had the same origin before the call.
    """

    outcome: UpsertOutcome
    item: RiskItem
    previous: RiskItem | None
    matches: int


def origin_key(item: RiskItem) -> str | None:
    """The question or pattern risk a register item came from; None for other sources.

    ``"question:<id>"`` for question-bank items and ``"pattern:<PATTERN_ID>:<title>"``
    for pattern items. Both parts are stored in ``tags`` and ``title``, also by 1.1.3.
    """
    if item.source == "question_bank" and item.tags and item.tags[0]:
        return f"question:{item.tags[0]}"
    if item.source == "pattern":
        pattern = next((tag for tag in item.tags if tag.startswith("pattern:")), None)
        if pattern is not None:
            return f"{pattern}:{item.title}"
    return None


def duplicate_origins(items: list[RiskItem]) -> dict[str, list[RiskItem]]:
    """Origins shared by more than one item, in register order (1.1.3 appended on re-runs)."""
    by_origin: dict[str, list[RiskItem]] = {}
    for item in items:
        key = origin_key(item)
        if key is not None:
            by_origin.setdefault(key, []).append(item)
    return {key: group for key, group in by_origin.items() if len(group) > 1}


class RiskEngine:
    """CRUD and scoring for risk items.

    Every change reads the register, writes it and records its audit entry inside one
    ``AuditEngine.unit_of_work()``, so concurrent writers cannot lose each other's
    updates, a write is never kept without its entry, and nothing changes in a project
    that fails its integrity check (``IntegrityError``).
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
        async with self._audit.unit_of_work():
            try:
                return await self._audit.read_register(system_id), False
            except RegisterNotFoundError:
                pass
            system = await self._audit.read_system(system_id)
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
            self._audit.wrote_register(system_id)
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
        async with self._audit.unit_of_work():
            register = await self._audit.read_register(system_id)
            register.items.append(item)
            await self._storage.write_register(system_id, register)
            self._audit.wrote_register(system_id)
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
        async with self._audit.unit_of_work():
            register = await self._audit.read_register(system_id)
            idx = next((i for i, r in enumerate(register.items) if r.id == item.id), None)
            if idx is None:
                raise RiskNotFoundError(str(item.id))
            old_score = register.items[idx].risk_score
            register.items[idx] = item
            await self._storage.write_register(system_id, register)
            self._audit.wrote_register(system_id)
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
        """Accept a risk item and store ``actor_identity`` as its ``accepted_by``.

        Raises
        ------
        RationaleRequiredError
            If the rationale is blank.
        ActorNameError
            If ``actor_identity`` is blank or not one line of text.
        """
        if not rationale.strip():
            raise RationaleRequiredError("Acceptance rationale is required and cannot be empty.")
        actor_identity = require_actor_name(actor_identity)
        async with self._audit.unit_of_work():
            register = await self._audit.read_register(system_id)
            item = self._resolve_risk_item(register.items, risk_id)
            risk_id = str(item.id)
            old_accepted = item.accepted
            item.accepted = True
            item.acceptance_rationale = rationale
            item.accepted_by = actor_identity
            await self._storage.write_register(system_id, register)
            self._audit.wrote_register(system_id)
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
        *,
        recorded_by: str | None = None,
    ) -> RiskItem:
        """Append a mitigation to a risk item and optionally re-score residual risk.

        ``recorded_by``, when given, is stored on the mitigation in the same change.

        Raises
        ------
        ActorNameError
            If the mitigation's ``recorded_by`` is blank or not one line of text.
        """
        name = recorded_by if recorded_by is not None else mitigation.recorded_by
        if name is not None:
            name = require_actor_name(name)
        async with self._audit.unit_of_work():
            register = await self._audit.read_register(system_id)
            item = self._resolve_risk_item(register.items, risk_id)
            mitigation.recorded_by = name
            item.mitigations.append(self._flag_vague(mitigation))
            if residual_likelihood is not None:
                item.residual_likelihood = Likelihood(residual_likelihood)
            if residual_severity is not None:
                item.residual_severity = Severity(residual_severity)
            await self._storage.write_register(system_id, register)
            self._audit.wrote_register(system_id)
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

    async def set_test_requirements(
        self, system_id: str, requirements: list[TestRequirement]
    ) -> bool:
        """Save the register's test requirements (event ``tests.generated``).

        Returns False, and records nothing, when the register already holds them.
        """
        async with self._audit.unit_of_work():
            register = await self._audit.read_register(system_id)
            if register.test_requirements == requirements:
                return False
            register.test_requirements = list(requirements)
            await self._storage.write_register(system_id, register)
            self._audit.wrote_register(system_id)
            await self._audit.record(
                "tests.generated",
                system_id,
                {
                    "count": len(requirements),
                    "risk_item_ids": sorted({str(r.risk_item_id) for r in requirements}),
                },
            )
        return True

    async def list_risks(
        self, system_id: str, dimension: RiskDimension | None = None
    ) -> list[RiskItem]:
        register = await self._storage.read_register(system_id)
        if dimension is not None:
            return [i for i in register.items if i.dimension == dimension]
        return register.items

    async def upsert_item(self, system_id: str, proposed: RiskItem) -> UpsertResult:
        """Add ``proposed``, or update the item that came from the same question or pattern.

        The same answer changes nothing and records nothing. A changed answer updates the
        likelihood, severity and knowledge-gap flag of the first matching item and
        records ``risk_item.updated`` with ``reason: "reassessment"``. Residual scores
        follow the new scores only while the item has no mitigation and its residual
        scores still equal its inherent ones. An acceptance is kept. Nothing is removed:
        when several items share the origin (a register re-run under 1.1.3), only the
        first is updated and ``matches`` says how many there are.

        Raises
        ------
        ValueError
            If ``proposed`` did not come from the question bank or a pattern.
        """
        key = origin_key(proposed)
        if key is None:
            raise ValueError("upsert_item needs an item from the question bank or a pattern.")
        async with self._audit.unit_of_work():
            register = await self._audit.read_register(system_id)
            matching = [item for item in register.items if origin_key(item) == key]
            if not matching:
                proposed.mitigations = [self._flag_vague(m) for m in proposed.mitigations]
                register.items.append(proposed)
                await self._storage.write_register(system_id, register)
                self._audit.wrote_register(system_id)
                await self._audit.record(
                    "risk_item.created",
                    system_id,
                    {
                        "risk_item_id": str(proposed.id),
                        "dimension": proposed.dimension,
                        "score": proposed.risk_score,
                    },
                )
                return UpsertResult("added", proposed, None, 0)
            existing = matching[0]
            if (existing.likelihood, existing.severity, existing.knowledge_gap) == (
                proposed.likelihood,
                proposed.severity,
                proposed.knowledge_gap,
            ):
                return UpsertResult("unchanged", existing, None, len(matching))
            previous = existing.model_copy(deep=True)
            residual_follows = not existing.mitigations and (
                existing.residual_likelihood,
                existing.residual_severity,
            ) == (existing.likelihood, existing.severity)
            existing.likelihood = proposed.likelihood
            existing.severity = proposed.severity
            existing.knowledge_gap = proposed.knowledge_gap
            if residual_follows:
                existing.residual_likelihood = proposed.likelihood
                existing.residual_severity = proposed.severity
            await self._storage.write_register(system_id, register)
            self._audit.wrote_register(system_id)
            await self._audit.record(
                "risk_item.updated",
                system_id,
                {
                    "risk_item_id": str(existing.id),
                    "old_score": previous.risk_score,
                    "new_score": existing.risk_score,
                    "reason": "reassessment",
                    "old_likelihood": int(previous.likelihood),
                    "new_likelihood": int(existing.likelihood),
                    "old_severity": int(previous.severity),
                    "new_severity": int(existing.severity),
                    "old_knowledge_gap": previous.knowledge_gap,
                    "new_knowledge_gap": existing.knowledge_gap,
                },
            )
            return UpsertResult("updated", existing, previous, len(matching))

    @staticmethod
    def _flag_vague(mitigation: Mitigation) -> Mitigation:
        mitigation.is_vague = is_vague_description(mitigation.description)
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
