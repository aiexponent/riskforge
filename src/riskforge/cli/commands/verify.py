"""riskforge verify: verify audit chain integrity."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Optional  # noqa: UP007 (Typer 0.12.3 needs Optional)

import typer
from rich.console import Console

if TYPE_CHECKING:
    from riskforge.models.receipt import Receipt

console = Console()


def cmd(
    project_dir: Path = typer.Option(Path("."), "--project-dir"),
    file: Optional[Path] = typer.Option(
        None, "--file", "-f", exists=True, dir_okay=False, help="Exported rmf.json to verify"
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help=(
            "Fail with exit 2 on any integrity warning, such as a register not yet covered "
            "by a fingerprint. Checks a project only, so it cannot be combined with --file."
        ),
    ),
    receipt: Optional[list[Path]] = typer.Option(
        None,
        "--receipt",
        help=(
            "Receipt file (from riskforge receipt) whose entry the audit log must still "
            "hold. Repeatable."
        ),
    ),
    trusted_key: Optional[list[Path]] = typer.Option(
        None,
        "--trusted-key",
        help=(
            "Public key file (the .pub from riskforge keygen) to trust. Each receipt must "
            "then be signed by a trusted key, and each signed audit entry too. Repeatable."
        ),
    ),
) -> None:
    """Verify integrity. Exits 2 if tampered or corrupt.

    With no --file, checks the whole project: the audit chain, the head file, each
    register against the fingerprint the log recorded last, each system file, and that
    no system or log was deleted. It reads only and takes no lock, so a read-only copy
    can be checked. With --file, verifies that a standalone exported rmf.json still
    matches its own self-verifying SHA-256 digest.

    With --strict, every warning the project check reports is a finding, so a project
    with a register last written before RiskForge 2.0, or with no audit.head.json, exits
    2 until its next change.

    With --receipt FILE, the project check also fails unless the audit log still holds,
    at the receipt's seq, the entry the receipt names. This catches a log cut back or
    rebuilt with audit.head.json rewritten to match, which the project check alone
    cannot see. The receipt's register fingerprint must also be the last one the log
    records for its system up to its seq. A signed receipt must verify with its own
    public key.

    With --trusted-key PUBFILE, each receipt must be signed by one of the trusted keys,
    and each signed audit entry must verify with one of them. Unsigned audit entries are
    then counted in a warning, so --strict --trusted-key fails unless every entry is
    signed. Without it, signed audit entries are reported as not checked. --receipt and --trusted-key check a project,
    so they cannot be combined with --file yet.

    Exit codes:
      0: valid, no tampering detected (warnings may be printed, never with --strict)
      1: a change is in progress or unfinished (.riskforge/txn.json), so nothing was
         checked; or an unexpected error
      2: integrity failure: the chain, head file, a register or system file, a receipt,
         a signature or the RMF file does not match what was recorded (CI-detectable);
         with --strict, also any integrity warning
      3: no project here, the file is missing or not a JSON RMF file, a receipt file is
         missing or not a receipt, a --trusted-key file is not an Ed25519 public key, or
         --strict, --receipt or --trusted-key was given with --file
    """
    from riskforge.cli.errors import EXIT_FAILED, EXIT_TAMPERED, fail, printable

    if file is not None:
        if strict:
            fail("--strict cannot be combined with --file: it applies to a project check.")
        if receipt or trusted_key:
            fail(
                "--receipt and --trusted-key check a project, so they cannot be combined "
                "with --file yet."
            )
        _verify_rmf_file(file)
        return

    from dataclasses import replace

    from rich.markup import escape

    from riskforge.cli.project import (
        load_trusted_keys,
        open_project_for_reading,
        print_integrity_failure,
        print_integrity_warnings,
    )
    from riskforge.engine.integrity import ChangeInProgressError, check_integrity_settled
    from riskforge.integrity.receipts import check_receipt

    trusted = load_trusted_keys(list(trusted_key or []))
    receipts, receipt_errors = _read_receipts(list(receipt or []))
    store = open_project_for_reading(project_dir)
    try:
        report = asyncio.run(check_integrity_settled(store, trusted_keys=trusted or None))
    except ChangeInProgressError as exc:
        fail(str(exc), EXIT_FAILED)

    if strict:
        report = report.strict()
    matched: list[tuple[Path, Receipt]] = []
    for path, parsed in receipts:
        found = check_receipt(parsed, report.entries, trusted, label=f"Receipt {path}")
        receipt_errors.extend(found)
        if not found:
            matched.append((path, parsed))
    print_integrity_warnings(report)
    if not report.ok or receipt_errors:
        print_integrity_failure(replace(report, errors=[*report.errors, *receipt_errors]))
        raise typer.Exit(EXIT_TAMPERED)
    console.print("[green]✓[/green] Audit chain verified: no tampering detected.")
    for path, parsed in matched:
        signer = f", signed by {parsed.key_id}" if parsed.key_id else ", not signed"
        trust = " (a trusted key)" if parsed.key_id and trusted else ""
        console.print(
            f"[green]✓[/green] Receipt {escape(printable(str(path)))}: the audit log holds "
            "its entry at "
            f"seq {parsed.seq}{signer}{trust}.",
            soft_wrap=True,
        )
    raise typer.Exit(0)


def _read_receipts(paths: list[Path]) -> tuple[list[tuple[Path, Receipt]], list[str]]:
    """Each receipt file read strictly; a refused one is a finding, an unreadable one exits 3."""
    from riskforge.cli.errors import fail
    from riskforge.integrity.receipts import (
        InvalidReceiptError,
        ReceiptFileError,
        read_receipt_file,
    )

    receipts: list[tuple[Path, Receipt]] = []
    errors: list[str] = []
    for path in paths:
        try:
            receipts.append((path, read_receipt_file(path)))
        except InvalidReceiptError as exc:
            errors.append(f"Receipt {path}: {exc}")
        except ReceiptFileError as exc:
            fail(f"Receipt {path}: {exc}")
    return receipts, errors


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
