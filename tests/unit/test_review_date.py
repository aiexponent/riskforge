"""The review date is whole calendar months after the assessment (D2 of the 2.0.0 test)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from riskforge.engine.audit import AuditEngine
from riskforge.engine.risk import RiskEngine, add_months
from riskforge.engine.system import SystemEngine
from riskforge.models.audit import AuditActor
from riskforge.models.system import AISystem
from riskforge.storage.filesystem import FileStore


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        # The independent test assessed on 2026-11-04 with 12 months and got 2027-10-30.
        ((2026, 11, 4), 12, (2027, 11, 4)),
        ((2026, 12, 15), 1, (2027, 1, 15)),
        ((2026, 1, 15), 24, (2028, 1, 15)),
        ((2026, 1, 31), 1, (2026, 2, 28)),
        ((2028, 1, 31), 1, (2028, 2, 29)),
        ((2028, 2, 29), 12, (2029, 2, 28)),
        ((2026, 11, 30), 3, (2027, 2, 28)),
        ((2026, 3, 31), 6, (2026, 9, 30)),
    ],
)
def test_add_months_keeps_the_day_or_clamps_to_the_month_end(
    start: tuple[int, int, int], months: int, expected: tuple[int, int, int]
) -> None:
    moment = datetime(*start, 9, 30, 15, tzinfo=UTC)
    assert add_months(moment, months) == datetime(*expected, 9, 30, 15, tzinfo=UTC)


def test_add_months_keeps_the_time_zone() -> None:
    zone = timezone(timedelta(hours=4))
    result = add_months(datetime(2026, 11, 4, 23, 59, tzinfo=zone), 12)
    assert result == datetime(2027, 11, 4, 23, 59, tzinfo=zone)
    assert result.tzinfo is zone


@pytest.mark.parametrize("months", [0, -1])
def test_create_register_refuses_a_review_period_under_one_month(
    tmp_path: Path, months: int
) -> None:
    store = FileStore(tmp_path)
    audit = AuditEngine(store, AuditActor(type="ci", identity="t"))

    async def run() -> None:
        await store.init_project("p", {})
        system = await SystemEngine(store, audit).create(
            AISystem(name="S", version="1", purpose="p", provider_name="P")
        )
        with pytest.raises(ValueError, match="at least 1"):
            await RiskEngine(store, audit).create_register(str(system.id), "A", "R", months)

    asyncio.run(run())
