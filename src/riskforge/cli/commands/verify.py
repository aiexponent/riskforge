"""riskforge verify: verify audit chain integrity."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional  # noqa: UP007 (Typer 0.12.3 needs Optional)

import typer
from rich.console import Console

console = Console()


def cmd(
    project_dir: Path = typer.Option(Path("."), "--project-dir"),
    file: Optional[Path] = typer.Option(
        None, "--file", "-f", exists=True, dir_okay=False, help="Exported rmf.json to verify"
    ),
) -> None:
    """Verify integrity. Exits 2 if tampered or corrupt.

    With no --file, checks the whole project: the audit chain, the head file, each
    register against the fingerprint the log recorded last, each system file, and that
    no system or log was deleted. It reads only and takes no lock, so a read-only copy
    can be checked. With --file, verifies that a standalone exported rmf.json still
    matches its own self-verifying SHA-256 digest.

    Exit codes:
      0: valid, no tampering detected (warnings may be printed)
      1: a change is in progress or unfinished (.riskforge/txn.json), so nothing was
         checked; or an unexpected error
      2: integrity failure: the chain, head file, a register or system file, or the RMF
         file does not match what was recorded (CI-detectable)
      3: no project here, or the file is missing or not a JSON RMF file
    """
    if file is not None:
        _verify_rmf_file(file)
        return

    from riskforge.cli.errors import EXIT_FAILED, EXIT_TAMPERED, fail
    from riskforge.cli.project import (
        open_project_for_reading,
        print_integrity_failure,
        print_integrity_warnings,
    )
    from riskforge.engine.integrity import ChangeInProgressError, check_integrity_settled

    store = open_project_for_reading(project_dir)
    try:
        report = asyncio.run(check_integrity_settled(store))
    except ChangeInProgressError as exc:
        fail(str(exc), EXIT_FAILED)

    print_integrity_warnings(report)
    if not report.ok:
        print_integrity_failure(report)
        raise typer.Exit(EXIT_TAMPERED)
    console.print("[green]✓[/green] Audit chain verified: no tampering detected.")
    raise typer.Exit(0)


def _verify_rmf_file(file: Path) -> None:
    """Verify a standalone exported rmf.json against its own SHA-256 digest.

    Recomputes the digest over the canonical JSON with the sha256_hash field
    blanked (the construction the exporter uses) and compares it to the stored
    value, so a tampered RMF is detectable by anyone holding only the file.
    """
    import hashlib
    import json

    from riskforge.cli.errors import fail

    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        fail(f"{file} is not a JSON RMF file (it is binary; verify the .json export).")
    except json.JSONDecodeError as exc:
        fail(f"{file} is not a JSON RMF file: {exc}")
    if not isinstance(data, dict):
        fail(f"{file} is not a JSON RMF file: the top level is not an object.")

    stored = data.get("sha256_hash", "")
    if not stored:
        console.print("[red]✗[/red] RMF has no sha256_hash field to verify.")
        raise typer.Exit(2)

    # Blank the integrity/provenance fields the exporter excludes from the digest
    # (see ExportEngine.export): sha256_hash, audit_entry_hash, signed_by.
    recompute_source = dict(data)
    recompute_source["sha256_hash"] = ""
    recompute_source["audit_entry_hash"] = ""
    recompute_source["signed_by"] = ""
    canonical = json.dumps(recompute_source, sort_keys=True, separators=(",", ":"))
    computed = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    if computed == stored:
        console.print(
            f"[green]✓[/green] RMF integrity verified. SHA-256 matches ({stored[:12]}...)."
        )
        raise typer.Exit(0)

    console.print(
        "[red]✗[/red] RMF INTEGRITY FAILURE. Content does not match its SHA-256 digest.\n"
        f"  stored:     {stored}\n"
        f"  recomputed: {computed}"
    )
    raise typer.Exit(2)
