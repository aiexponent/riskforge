#!/usr/bin/env python
"""RiskForge performance benchmark.

Two measurements:

1. audit append: build a hash-chained audit log of N entries. This is the path
   the O(n) tail-chaining fix targets; it should scale linearly.
2. add_risk: the full engine path (append a risk item, which rewrites the whole
   register YAML plus one audit entry). The register rewrite is O(n) per call, so
   this path is O(n^2) in the number of items by design of the flat-file store;
   it is fast at the register sizes a real assessment produces (tens of items).

The first two run their loop inside one ``AuditEngine.unit_of_work()``, so the
integrity check that opens every change runs once. A third row times 50 ``add_risk``
calls as separate changes, each running the full check (which reads the whole log and
every register, as every CLI command does once), so a slower check shows up there.

    python benchmarks/perf.py

Timings are wall-clock on the current machine and are indicative, not a guarantee.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from riskforge.engine.audit import AuditEngine
from riskforge.engine.risk import RiskEngine
from riskforge.models.audit import AuditActor
from riskforge.models.register import RiskRegister
from riskforge.models.risk import Likelihood, RiskDimension, RiskItem, Severity
from riskforge.models.system import AISystem, AnnexIIICategory
from riskforge.storage.filesystem import FileStore

_DIMS = list(RiskDimension)


def _system() -> AISystem:
    return AISystem(
        name="Bench",
        version="1.0",
        purpose="benchmark",
        provider_name="Bench",
        annex_iii_category=AnnexIIICategory.essential_services,
        annex_iii_self_classification_documented=True,
    )


def _item(i: int) -> RiskItem:
    return RiskItem(
        dimension=_DIMS[i % len(_DIMS)],
        title=f"risk {i}",
        description="benchmark risk item",
        source="manual",
        likelihood=Likelihood.possible,
        severity=Severity.moderate,
        residual_likelihood=Likelihood.unlikely,
        residual_severity=Severity.minor,
    )


async def _setup(d: Path) -> tuple[FileStore, str]:
    store = FileStore(d)
    await store.init_project("bench", {})
    system = _system()
    sid = str(system.id)
    await store.write_system(sid, system)
    await store.write_register(
        sid,
        RiskRegister(
            system=system,
            assessor_name="A",
            assessor_role="B",
            assessment_date=datetime.now(UTC),
            review_date=datetime.now(UTC) + timedelta(days=365),
            question_bank_version="1.0.0",
        ),
    )
    return store, sid


async def _bench_audit(size: int) -> tuple[float, float]:
    with tempfile.TemporaryDirectory() as tmp:
        store, sid = await _setup(Path(tmp))
        audit = AuditEngine(store, AuditActor(type="ci", identity="bench"))
        start = time.perf_counter()
        # One unit of work, so the integrity check runs once (each separate change runs
        # its own full check, which is O(n) in the log).
        async with audit.unit_of_work():
            for _ in range(size):
                await audit.record("bench.event", sid, {})
        append_total = time.perf_counter() - start
        start = time.perf_counter()
        await store.verify_chain()
        return append_total, time.perf_counter() - start


async def _bench_add_risk(size: int) -> float:
    with tempfile.TemporaryDirectory() as tmp:
        store, sid = await _setup(Path(tmp))
        audit = AuditEngine(store, AuditActor(type="ci", identity="bench"))
        engine = RiskEngine(store, audit)
        start = time.perf_counter()
        async with audit.unit_of_work():
            for i in range(size):
                await engine.add_risk(sid, _item(i))
        return time.perf_counter() - start


async def _bench_separate_changes(size: int) -> float:
    """``add_risk`` with each call its own change, so each runs the full integrity check."""
    with tempfile.TemporaryDirectory() as tmp:
        store, sid = await _setup(Path(tmp))
        engine = RiskEngine(store, AuditEngine(store, AuditActor(type="ci", identity="bench")))
        start = time.perf_counter()
        for i in range(size):
            await engine.add_risk(sid, _item(i))
        return time.perf_counter() - start


async def main() -> None:
    print("audit append (tail-chained, O(n)):")
    print(f"  {'entries':>8} {'total (s)':>12} {'per entry (ms)':>16} {'verify (s)':>12}")
    for size in [100, 500, 1000, 2000]:
        total, verify = await _bench_audit(size)
        print(f"  {size:>8} {total:>12.3f} {total / size * 1000:>16.3f} {verify:>12.3f}")

    print("\nadd_risk, one unit of work (register rewrite + audit, each call O(n) in items):")
    print(f"  {'items':>8} {'total (s)':>12} {'per item (ms)':>16}")
    for size in [10, 50, 100, 200]:
        total = await _bench_add_risk(size)
        print(f"  {size:>8} {total:>12.3f} {total / size * 1000:>16.3f}")

    print("\nadd_risk, a separate change per call (each also runs the full integrity check):")
    print(f"  {'items':>8} {'total (s)':>12} {'per item (ms)':>16}")
    for size in [50]:
        total = await _bench_separate_changes(size)
        print(f"  {size:>8} {total:>12.3f} {total / size * 1000:>16.3f}")


if __name__ == "__main__":
    asyncio.run(main())
