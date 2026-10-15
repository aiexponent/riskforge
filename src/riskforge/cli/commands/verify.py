"""riskforge verify: verify audit chain integrity."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, Optional  # noqa: UP007 (Typer 0.12.3 needs Optional)

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
            "by a fingerprint. A file check has no warnings, so it cannot be combined with "
            "--file."
        ),
    ),
    receipt: Optional[list[Path]] = typer.Option(
        None,
        "--receipt",
        help=(
            "Receipt file (from riskforge receipt, or an exported rmf.json) whose entry the "
            "audit log, or with --file the file's chain proof, must still hold. Repeatable."
        ),
    ),
    trusted_key: Optional[list[Path]] = typer.Option(
        None,
        "--trusted-key",
        help=(
            "Public key file (the .pub from riskforge keygen) to trust. Each receipt must "
            "then be signed by a trusted key, and each signed audit entry too. With --file, "
            "the file's signature, sign-offs and receipt too. Repeatable."
        ),
    ),
) -> None:
    """Verify integrity. Exits 2 if tampered or corrupt.

    With no --file, checks the whole project: the audit chain, the head file, each
    register against the fingerprint the log recorded last, each system file, and that
    no system or log was deleted. It reads only and takes no lock, so a read-only copy
    can be checked. With --file, checks a standalone exported rmf.json instead: the
    schema it declares, its content digest, its public keys, signatures and sign-offs,
    its chain proof (linked and hashed, ending at the register in the file) and its
    receipt (naming the last chain proof entry). A file that declares RMF schema 1.0.0
    gets the digest check only, and fails with --trusted-key or --receipt, since it
    cannot carry a signature.

    With --strict, every warning the project check reports is a finding, so a project
    with a register last written before RiskForge 2.0, or with no audit.head.json, exits
    2 until its next change. A file check has no warnings: what it does not prove, such
    as who signed without --trusted-key, it states when it passes. So --strict cannot be
    combined with --file.

    With --receipt FILE, the project check also fails unless the audit log still holds,
    at the receipt's seq, the entry the receipt names. This catches a log cut back or
    rebuilt with audit.head.json rewritten to match, which the project check alone
    cannot see. The receipt's register fingerprint must also be the last one the log
    records for its system up to its seq. A signed receipt must verify with its own
    public key. With --file, each receipt is checked against the file's chain proof
    instead, so a receipt kept from an older export checks a newer one.

    With --trusted-key PUBFILE, each receipt must be signed by one of the trusted keys,
    and each signed audit entry must verify with one of them. Unsigned audit entries are
    then counted in a warning, so --strict --trusted-key fails unless every entry is
    signed. Without it, signed audit entries are reported as not checked. With --file,
    the file must carry an RMF signature, and its RMF signatures, sign-offs and embedded
    receipt must all be signed by a trusted key.

    Exit codes:
      0: valid, no tampering detected (warnings may be printed, never with --strict)
      1: a change is in progress or unfinished (.riskforge/txn.json), so nothing was
         checked; or an unexpected error
      2: integrity failure: the chain, head file, a register or system file, a receipt,
         a signature or the RMF file does not match what was recorded (CI-detectable);
         with --strict, also any integrity warning
      3: no project here, the file is missing or not a JSON RMF file, a receipt file is
         missing or not a receipt, a --trusted-key file is not an Ed25519 public key, or
         --strict was given with --file
    """
    from riskforge.cli.errors import EXIT_FAILED, EXIT_TAMPERED, fail, printable
    from riskforge.cli.project import load_trusted_keys

    if file is not None and strict:
        fail("--strict cannot be combined with --file: a file check has no warnings.")
    trusted = load_trusted_keys(list(trusted_key or []))
    receipts, receipt_errors = _read_receipts(list(receipt or []))
    if file is not None:
        _verify_rmf_file(file, trusted, receipts, receipt_errors, trust_required=bool(receipt))

    from dataclasses import replace

    from rich.markup import escape

    from riskforge.cli.project import (
        open_project_for_reading,
        print_integrity_failure,
        print_integrity_warnings,
    )
    from riskforge.engine.integrity import ChangeInProgressError, check_integrity_settled
    from riskforge.integrity.receipts import check_receipt

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


def _verify_rmf_file(
    file: Path,
    trusted: list[str],
    receipts: list[tuple[Path, Receipt]],
    receipt_errors: list[str],
    *,
    trust_required: bool,
) -> NoReturn:
    """Verify a standalone exported rmf.json as ADR-04 section 6 orders it, then exit.

    The file is read strictly (a duplicate key, a non-finite number or an integer too
    long to read exits 2), and ``check_rmf_document`` checks it with the trusted keys
    and receipts given. ``receipt_errors`` are receipt files already refused.
    """
    from rich.markup import escape

    from riskforge.cli.errors import EXIT_TAMPERED, fail, printable
    from riskforge.integrity.rmf import (
        RmfFileError,
        UnsupportedRmfVersionError,
        check_rmf_document,
        read_rmf_file,
    )
    from riskforge.integrity.strict_json import NumberTooLongError, StrictJsonError

    shown = escape(printable(str(file)))
    try:
        data = read_rmf_file(file)
    except RmfFileError as exc:
        fail(f"{file} is not a JSON RMF file: {exc}")
    except (StrictJsonError, NumberTooLongError) as exc:
        console.print(
            f"[red]✗[/red] {shown} holds {escape(printable(str(exc)))}, which RiskForge "
            "never writes.",
            soft_wrap=True,
        )
        raise typer.Exit(EXIT_TAMPERED) from None

    labelled = [(f"Receipt {path}", parsed) for path, parsed in receipts]
    try:
        result = check_rmf_document(
            data, trusted, labelled, trust_required=trust_required or bool(trusted)
        )
    except UnsupportedRmfVersionError as exc:
        fail(f"{file}: {exc}")

    findings = [*result.findings, *receipt_errors]
    if not findings:
        stored = escape(printable(str(result.stored_digest)))
        console.print(
            f"[green]✓[/green] RMF integrity verified. It validates against RMF schema "
            f"{result.version} and its SHA-256 matches ({stored[:12]}...).",
            soft_wrap=True,
        )
        for note in result.notes:
            console.print(f"  {escape(printable(note))}", soft_wrap=True, highlight=False)
        raise typer.Exit(0)
    console.print(f"[red]✗[/red] RMF INTEGRITY FAILURE in {shown}:", soft_wrap=True)
    for finding in findings:
        console.print(f"  - {escape(printable(finding))}", soft_wrap=True, highlight=False)
    raise typer.Exit(EXIT_TAMPERED)
