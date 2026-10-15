"""riskforge receipt: a record of the audit chain head, to keep outside the project."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional  # noqa: UP007 (Typer 0.12.3 needs Optional)

import typer
from rich.console import Console

if TYPE_CHECKING:
    from riskforge.engine.integrity import IntegrityReport
    from riskforge.models.receipt import Receipt
    from riskforge.storage.filesystem import FileStore

console = Console()


def cmd(
    system_id: str = typer.Argument(..., help="System ID the receipt is taken for"),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="File to write the receipt to (never overwritten). Without it, the receipt is printed.",
    ),
    sign: Optional[Path] = typer.Option(
        None, "--sign", help="Ed25519 private key file to sign the receipt with (riskforge keygen)"
    ),
    project_dir: Path = typer.Option(Path("."), "--project-dir"),
) -> None:
    """Take a receipt for the last entry of the audit log.

    A receipt names the seq and entry_hash of the last audit entry, and the latest
    register fingerprint the log records for the system. Keep it outside the project,
    for example with whoever relies on the register. Later, `riskforge verify --receipt
    FILE` exits 2 if the log no longer holds that entry, even when audit.jsonl and
    audit.head.json were cut back or rebuilt together.

    The project is checked first, as `riskforge verify` checks it, and nothing is taken
    of a project that fails. The project is only read. With --output the file is created
    with mode 600 on Linux and macOS.

    Exit codes:
      0: receipt printed or written
      1: a change is in progress or unfinished (.riskforge/txn.json)
      2: the project failed its integrity check; nothing was written
      3: no project or no such system, the output file exists or cannot be written,
         or the --sign key file is refused
    """
    from rich.markup import escape

    from riskforge.cli.errors import fail
    from riskforge.cli.project import (
        load_signer,
        read_system_or_fail,
        run_read_checked_with_report,
    )
    from riskforge.engine.receipts import NoChainEntryError, issue_receipt
    from riskforge.integrity.receipts import ReceiptFileError, receipt_json, write_receipt_file

    signer = load_signer(sign) if sign is not None else None
    if output is not None and (output.exists() or output.is_symlink()):
        fail(
            f"{output} already exists. RiskForge never overwrites a receipt; choose another --output."
        )

    async def _issue(store: FileStore, report: IntegrityReport) -> Receipt:
        await read_system_or_fail(store, system_id)
        try:
            return issue_receipt(report, system_id, signer)
        except NoChainEntryError as exc:
            fail(str(exc))

    receipt = run_read_checked_with_report(project_dir, _issue)
    if output is None:
        typer.echo(receipt_json(receipt), nl=False)
        return
    try:
        write_receipt_file(output, receipt)
    except ReceiptFileError as exc:
        fail(str(exc))
    signed = f", signed by {receipt.key_id}" if receipt.key_id else ""
    console.print(
        f"[green]✓[/green] Receipt for seq {receipt.seq} written to {escape(str(output))}{signed}.",
        soft_wrap=True,
    )
    console.print(
        "  Keep it outside the project. Check it with: riskforge verify --receipt FILE",
        soft_wrap=True,
    )
