"""Four processes adding 25 risks each lose nothing (PRD-331: before the fix 38 of 100 survived)."""

from __future__ import annotations

import asyncio
import json
import multiprocessing
from pathlib import Path

from rf_testkit import add_risks_worker
from riskforge.engine.audit import AuditEngine
from riskforge.engine.risk import RiskEngine
from riskforge.engine.system import SystemEngine
from riskforge.models.audit import AuditActor
from riskforge.models.system import AISystem
from riskforge.storage.filesystem import FileStore

PROCESSES = 4
PER_PROCESS = 25
# Slow shared CI runners (macOS in particular) can take far longer than a laptop.
JOIN_TIMEOUT_SECONDS = 600


def test_four_processes_lose_no_updates(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    system = AISystem(name="C", version="1", purpose="concurrency probe", provider_name="P")
    sid = str(system.id)

    async def setup() -> None:
        await store.init_project("p", {})
        audit = AuditEngine(store, AuditActor(type="human", identity="setup"))
        await SystemEngine(store, audit).create(system)
        await RiskEngine(store, audit).create_register(sid, "A", "B")

    asyncio.run(setup())
    context = multiprocessing.get_context("spawn")
    workers = [
        context.Process(target=add_risks_worker, args=(str(tmp_path), sid, worker, PER_PROCESS))
        for worker in range(PROCESSES)
    ]
    for worker in workers:
        worker.start()
    try:
        for worker in workers:
            worker.join(timeout=JOIN_TIMEOUT_SECONDS)
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.kill()
                worker.join()
    register = asyncio.run(store.read_register(sid))
    exit_codes = [worker.exitcode for worker in workers]
    assert exit_codes == [0] * PROCESSES, f"exit codes {exit_codes}, {len(register.items)} items"
    lines = (tmp_path / ".riskforge" / "audit.jsonl").read_text().splitlines()
    events = [json.loads(line)["event"] for line in lines]
    assert len(register.items) == PROCESSES * PER_PROCESS
    assert len({item.title for item in register.items}) == PROCESSES * PER_PROCESS
    assert events.count("risk_item.created") == PROCESSES * PER_PROCESS
    ok, errors = asyncio.run(store.verify_chain())
    assert ok, errors
