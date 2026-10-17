"""Helpers shared by tests: run the riskforge CLI with the network blocked."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

NETBLOCK_DIR = Path(__file__).resolve().parent / "netblock"
# Set only by the release workflow: the published-schema check must then run (tests/release).
RELEASE_ENV = "RISKFORGE_RELEASE_CHECK"

RF_BIN = str(Path(sys.executable).parent / "riskforge")
if not Path(RF_BIN).exists():
    RF_BIN = shutil.which("riskforge") or RF_BIN


def offline_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """os.environ plus a PYTHONPATH that loads tests/netblock/sitecustomize.py first."""
    env = dict(os.environ)
    paths = [str(NETBLOCK_DIR)]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    # Typer forces a styled terminal when any of these is set (GitHub Actions sets the
    # first), and NO_COLOR alone does not remove bold, so output would differ from local runs.
    for var in ("GITHUB_ACTIONS", "FORCE_COLOR", "PY_COLORS"):
        env.pop(var, None)
    # A developer's own RISKFORGE_ACTOR would otherwise answer `--by` for every test.
    env.pop("RISKFORGE_ACTOR", None)
    env["NO_COLOR"] = "1"
    env["COLUMNS"] = "200"
    if extra:
        env.update(extra)
    return env


def run_rf(
    args: list[str],
    cwd: Path | str | None = None,
    input_text: str | None = None,
    timeout: int = 180,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run ``riskforge <args>`` offline, with *env* added to the environment.

    The result gains ``.output`` (stdout plus stderr).
    """
    stdin_kwargs = (
        {"input": input_text} if input_text is not None else {"stdin": subprocess.DEVNULL}
    )
    result = subprocess.run(
        [RF_BIN, *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=offline_env(env),
        timeout=timeout,
        **stdin_kwargs,
    )
    result.output = result.stdout + result.stderr  # type: ignore[attr-defined]
    return result


def add_risks_worker(project: str, system_id: str, worker_id: int, count: int) -> None:
    """Child-process body for the concurrency test: add ``count`` items through RiskEngine."""
    import asyncio

    from riskforge.engine.audit import AuditEngine
    from riskforge.engine.risk import RiskEngine
    from riskforge.models.audit import AuditActor
    from riskforge.models.risk import Likelihood, RiskDimension, RiskItem, Severity
    from riskforge.storage.filesystem import FileStore

    async def run() -> None:
        store = FileStore(Path(project))
        actor = AuditActor(type="human", identity=f"worker-{worker_id}")
        engine = RiskEngine(store, AuditEngine(store, actor))
        for n in range(count):
            await engine.add_risk(
                system_id,
                RiskItem(
                    dimension=RiskDimension.privacy,
                    title=f"w{worker_id}-{n}",
                    description="concurrency probe",
                    likelihood=Likelihood(2),
                    severity=Severity(2),
                    residual_likelihood=Likelihood(2),
                    residual_severity=Severity(2),
                ),
            )

    asyncio.run(run())


def pdf_text(path: Path) -> str:
    """Text of every page of a PDF, as a reader sees it."""
    from pypdf import PdfReader

    return "\n".join(page.extract_text() for page in PdfReader(str(path)).pages)


def with_provenance(rmf):
    """``rmf`` with the chain proof and receipt every export embeds: one checkpoint entry.

    For tests that build a RiskManagementFile by hand and validate it against schema
    1.1.0, which requires both blocks.
    """
    from datetime import UTC, datetime

    from riskforge.integrity.canonical import document_fingerprint
    from riskforge.integrity.chain import GENESIS_PREV_HASH, compute_entry_hash
    from riskforge.integrity.receipts import build_receipt
    from riskforge.models.audit import AuditActor, AuditEntry
    from riskforge.models.rmf import ChainProof

    system_id = str(rmf.register.system.id)
    fingerprint = document_fingerprint(rmf.register.model_dump(mode="json"))
    entry = AuditEntry(
        seq=0,
        event="register.checkpoint",
        timestamp=datetime.now(UTC),
        actor=AuditActor(type="human", identity="test"),
        system_id=system_id,
        payload={"riskforge_version": "test"},
        prev_hash=GENESIS_PREV_HASH,
        register_fingerprint=fingerprint,
    )
    entry.entry_hash = compute_entry_hash(entry)
    rmf.chain_proof = ChainProof(scope="project", entries=[entry])
    rmf.receipt = build_receipt(entry, system_id, fingerprint)
    return rmf
