"""RiskForge CLI entry point."""

from __future__ import annotations

import sys

import click
import typer

from riskforge.cli.errors import EXIT_FAILED, EXIT_OK, EXIT_TAMPERED, EXIT_USAGE, err_console
from riskforge.storage.errors import (
    AuditLogCorruptError,
    ProjectLockedError,
    StoredFileCorruptError,
)


def _version_callback(value: bool) -> None:
    """Eager --version callback. Separate function avoids naming conflict with subcommand options."""
    if value:
        from importlib.metadata import version as pkg_version

        typer.echo(
            f"RiskForge v{pkg_version('riskforge')} | Apache 2.0 | Zero telemetry | aiexponent.com"
        )
        raise typer.Exit()


app = typer.Typer(
    name="riskforge",
    help="EU AI Act Article 9 risk management system, by AI Exponent LLC",
    no_args_is_help=True,
)


@app.callback(invoke_without_command=True)
def main(
    _version: bool = typer.Option(  # noqa: B008
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        expose_value=False,
        help="Show version and exit.",
    ),
) -> None:
    """RiskForge: EU AI Act Article 9 Risk Management System CLI."""


# Register subcommands (lazy imports, no business logic at import time)
from riskforge.cli.commands import (  # noqa: E402
    assess,
    diff,
    export,
    import_cmd,
    init,
    risk,
    system,
    tests_cmd,
    validate,
    verify,
)

app.add_typer(system.app, name="system")
app.add_typer(risk.app, name="risk")
app.add_typer(tests_cmd.app, name="tests")

app.command("init")(init.cmd)
app.command("assess")(assess.cmd)
app.command("validate")(validate.cmd)
app.command("export")(export.cmd)
app.command("verify")(verify.cmd)
app.command("diff")(diff.cmd)
app.command("import")(import_cmd.cmd)


def _show_click_error(exc: click.ClickException) -> None:
    """Print a Click error the way Typer's standalone mode does."""
    from typer import rich_utils

    rich_format_error = getattr(rich_utils, "rich_format_error", None)
    if rich_format_error is None:
        exc.show()
    else:
        rich_format_error(exc)


def _one_line_error(message: str) -> None:
    from rich.markup import escape

    err_console.print(f"[red]✗[/red] {escape(message)}", highlight=False, soft_wrap=True)


def run() -> None:
    """Console entry point.

    Click reports usage errors with exit 2, which RiskForge reserves for integrity
    failures, so they leave with EXIT_USAGE instead. A held project lock exits 1, and a
    corrupt audit log or a stored file that does not parse exits 2, each with one line
    and no traceback.
    """
    try:
        code = app(prog_name="riskforge", standalone_mode=False)
    except click.UsageError as exc:
        # Click 8.2+ raises NoArgsIsHelpError for a bare `riskforge`: help, not an error.
        no_args_is_help = getattr(click.exceptions, "NoArgsIsHelpError", None)
        if no_args_is_help is not None and isinstance(exc, no_args_is_help):
            exc.show()
            sys.exit(EXIT_OK)
        _show_click_error(exc)
        sys.exit(EXIT_USAGE)
    except click.ClickException as exc:
        _show_click_error(exc)
        sys.exit(exc.exit_code)
    except click.exceptions.Abort:
        click.echo("Aborted.", err=True)
        sys.exit(EXIT_FAILED)
    except ProjectLockedError as exc:
        _one_line_error(str(exc))
        sys.exit(EXIT_FAILED)
    except AuditLogCorruptError as exc:
        _one_line_error(f"{exc} Run `riskforge verify` for details.")
        sys.exit(EXIT_TAMPERED)
    except StoredFileCorruptError as exc:
        message = str(exc)
        if "riskforge verify" not in message:
            message += " Run `riskforge verify` for details."
        _one_line_error(message)
        sys.exit(EXIT_TAMPERED)
    sys.exit(code if isinstance(code, int) else EXIT_OK)
