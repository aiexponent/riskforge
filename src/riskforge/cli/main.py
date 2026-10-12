"""RiskForge CLI entry point."""

from __future__ import annotations

import typer


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
    help="EU AI Act Article 9 Risk Management System — AI Exponent LLC",
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
    """RiskForge — EU AI Act Article 9 Risk Management System CLI."""


# Register subcommands (lazy imports — no business logic at import time)
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
