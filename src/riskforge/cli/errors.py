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

# Bidirectional controls: they can make text display in another order than it is stored.
_BIDI_CONTROLS = frozenset(
    ["\u061c", "\u200e", "\u200f"]
    + [chr(c) for c in range(0x202A, 0x202F)]
    + [chr(c) for c in range(0x2066, 0x206A)]
)


def _visible(char: str) -> str:
    code = ord(char)
    if code < 0x20 or 0x7F <= code <= 0x9F:  # C0, DEL and C1 controls
        return {"\n": "\\n", "\t": "\\t", "\r": "\\r"}.get(char, f"\\x{code:02x}")
    if char in _BIDI_CONTROLS:
        return f"\\u{code:04x}"
    return char


def printable(text: str, *, keep_newlines: bool = False) -> str:
    """``text`` with control and bidirectional control characters shown as escapes.

    Messages can quote text from files RiskForge reads, such as a key name in a receipt
    file. Rich's ``escape`` only escapes markup, so an escape sequence there would
    otherwise reach the terminal.
    """
    return "".join(char if keep_newlines and char == "\n" else _visible(char) for char in text)


def fail(message: str, code: int = EXIT_USAGE) -> NoReturn:
    """Print ``✗ message`` to stderr and exit with *code* (usage error by default)."""
    err_console.print(
        f"[red]✗[/red] {escape(printable(message, keep_newlines=True))}",
        highlight=False,
        soft_wrap=True,
    )
    raise typer.Exit(code)
