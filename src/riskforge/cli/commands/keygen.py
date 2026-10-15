"""riskforge keygen: create an Ed25519 key pair for signing."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

console = Console()


def cmd(
    output: Path = typer.Option(
        ...,
        "--output",
        "-o",
        help="Private key file to create (PEM). The public key goes to <output>.pub.",
    ),
) -> None:
    """Create an Ed25519 signing key pair.

    The private key is not encrypted. On Linux and macOS it is written with mode 600
    (readable only by its owner); on Windows it takes the folder's permissions. Keep it
    outside the project directory and out of version control. Give the .pub file to anyone who
    checks your signatures. An existing file is never overwritten: when either file
    exists, or the directory is missing, keygen writes nothing and exits 3.
    """
    import os

    from rich.markup import escape

    from riskforge.cli.errors import fail
    from riskforge.integrity.signing import (
        KeyFileError,
        key_id_for,
        public_key_path,
        write_key_pair,
    )

    try:
        public_b64 = write_key_pair(output)
    except KeyFileError as exc:
        fail(str(exc))
    protection = "mode 600, not encrypted" if os.name == "posix" else "not encrypted"
    console.print(f"[green]✓[/green] Private key: {escape(str(output))} ({protection})")
    console.print(f"  Public key file: {escape(str(public_key_path(output)))}")
    console.print(f"  Key id: {key_id_for(public_b64)}")
    console.print(f"  Public key: {public_b64}", soft_wrap=True)
