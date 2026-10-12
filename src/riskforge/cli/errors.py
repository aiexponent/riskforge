"""Exit codes and the one-line failure helper every command uses."""

from __future__ import annotations

from typing import NoReturn

import typer
from rich.console import Console
from rich.markup import escape

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_TAMPERED = 2
EXIT_USAGE = 3

err_console = Console(stderr=True)


def fail(message: str, code: int = EXIT_USAGE) -> NoReturn:
    """Print ``✗ message`` to stderr and exit with *code* (usage error by default)."""
    err_console.print(f"[red]✗[/red] {escape(message)}", highlight=False)
    raise typer.Exit(code)
