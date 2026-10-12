"""riskforge verify — verify audit chain integrity."""

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

    With no --file, verifies the project's append-only audit chain. With --file,
    verifies that a standalone exported rmf.json still matches its own self-verifying
    SHA-256 digest.

    Exit codes:
      0: valid, no tampering detected
      1: unexpected error
      2: chain corrupt, or the RMF file does not match its digest (CI-detectable)
      3: no project here, or the file is missing or not a JSON RMF file
    """
    if file is not None:
        _verify_rmf_file(file)
        return

    from riskforge.cli.project import open_project

    store = open_project(project_dir)
    is_valid, violations = asyncio.run(store.verify_chain())

    if is_valid:
        console.print("[green]✓[/green] Audit chain verified: no tampering detected.")
        raise typer.Exit(0)
    else:
        console.print("[red]✗[/red] Audit chain CORRUPT. Tampering or corruption detected:")
        for v in violations:
            console.print(f"  [red]•[/red] {v}")
        raise typer.Exit(2)  # Exit code 2: detectable by CI pipelines


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
