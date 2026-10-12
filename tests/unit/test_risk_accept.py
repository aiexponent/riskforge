"""Regression tests for `risk accept` id resolution (B3).

`risk list` prints the first 8 characters of each risk id and the `accept`
`--help` promised "Risk item ID (or first 8 chars)", but `accept_risk` matched
only the full UUID string and raised an uncaught `RiskNotFoundError` (a traceback)
for the 8-char form. These tests pin prefix resolution and clean error behaviour.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from riskforge.engine.audit import AuditEngine
from riskforge.engine.risk import (
    AmbiguousRiskIdError,
    RiskEngine,
    RiskNotFoundError,
)
from riskforge.models.audit import AuditActor
from riskforge.models.register import RiskRegister
from riskforge.models.risk import Likelihood, RiskDimension, RiskItem, Severity
from riskforge.models.system import AISystem, AnnexIIICategory
from riskforge.storage.filesystem import FileStore


def _item(rid: str | None = None) -> RiskItem:
    kwargs = {}
    if rid is not None:
        kwargs["id"] = UUID(rid)
    return RiskItem(
        dimension=RiskDimension.privacy,
        title="Risk",
        description="Desc.",
        source="manual",
        likelihood=Likelihood.possible,
        severity=Severity.moderate,
        residual_likelihood=Likelihood.likely,
        residual_severity=Severity.major,
        **kwargs,
    )


async def _engine_with_items(tmp_path: Path, items: list[RiskItem]) -> tuple[RiskEngine, str]:
    store = FileStore(tmp_path)
    system = AISystem(
        name="S",
        version="1.0",
        purpose="p",
        provider_name="prov",
        annex_iii_category=AnnexIIICategory.essential_services,
    )
    sid = str(system.id)
    await store.init_project("proj", {"system_name": system.name})
    await store.write_system(sid, system)
    reg = RiskRegister(
        system=system,
        assessor_name="A",
        assessor_role="B",
        assessment_date=datetime.now(UTC),
        review_date=datetime.now(UTC) + timedelta(days=365),
        question_bank_version="1.0.0",
    )
    await store.write_register(sid, reg)
    audit = AuditEngine(store, AuditActor(type="human", identity="t"))
    engine = RiskEngine(store, audit)
    for it in items:
        await engine.add_risk(sid, it)
    return engine, sid


@pytest.mark.asyncio
async def test_accept_by_full_id(tmp_path: Path) -> None:
    item = _item()
    engine, sid = await _engine_with_items(tmp_path, [item])
    accepted = await engine.accept_risk(sid, str(item.id), "reviewed", "t")
    assert accepted.accepted is True
    assert accepted.id == item.id


@pytest.mark.asyncio
async def test_accept_by_8char_prefix(tmp_path: Path) -> None:
    """The 8-char prefix that `risk list` displays must resolve."""
    item = _item()
    engine, sid = await _engine_with_items(tmp_path, [item])
    accepted = await engine.accept_risk(sid, str(item.id)[:8], "reviewed", "t")
    assert accepted.accepted is True
    assert accepted.id == item.id


@pytest.mark.asyncio
async def test_accept_unknown_id_raises_not_found(tmp_path: Path) -> None:
    engine, sid = await _engine_with_items(tmp_path, [_item()])
    with pytest.raises(RiskNotFoundError):
        await engine.accept_risk(sid, "deadbeef", "reviewed", "t")


@pytest.mark.asyncio
async def test_accept_ambiguous_prefix_raises(tmp_path: Path) -> None:
    a = _item("aaaaaaaa-0000-0000-0000-000000000001")
    b = _item("aaaaaaaa-0000-0000-0000-000000000002")
    engine, sid = await _engine_with_items(tmp_path, [a, b])
    with pytest.raises(AmbiguousRiskIdError):
        await engine.accept_risk(sid, "aaaaaaaa", "reviewed", "t")
