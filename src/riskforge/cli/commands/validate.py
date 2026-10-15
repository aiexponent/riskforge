"""riskforge validate: run 8 export readiness gates."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def cmd(
    system_id: str = typer.Argument(..., help="System ID to validate"),
    project_dir: Path = typer.Option(Path("."), "--project-dir"),
    force: bool = typer.Option(False, "--force", help="Export even if FAIL gates present"),
) -> None:
    """Run the 8 Article 9 readiness gates before export.

    All FAIL gates must pass before riskforge export will proceed
    (unless --force is supplied). WARN gates are advisory.
    """
    from riskforge.cli.errors import EXIT_FAILED
    from riskforge.cli.project import read_register_or_fail, run_read_checked
    from riskforge.engine.validate import ValidateEngine

    register = run_read_checked(project_dir, lambda store: read_register_or_fail(store, system_id))

    engine = ValidateEngine()
    results = engine.run(register)

    table = Table(title="Validation Results", show_header=True)
    table.add_column("Gate", style="bold")
    table.add_column("Description")
    table.add_column("Status")
    table.add_column("Details", max_width=60)

    for r in results:
        status_colour = {"PASS": "green", "WARN": "yellow", "FAIL": "red"}[r.status.value]
        table.add_row(
            r.gate_id,
            r.description,
            f"[{status_colour}]{r.status.value}[/{status_colour}]",
            r.details or "",
        )

    console.print(table)

    if engine.has_failures(results):
        console.print("\n[red]✗[/red] Validation failed. Fix FAIL gates before export.")
        if not force:
            raise typer.Exit(EXIT_FAILED)
        else:
            console.print("[yellow]--force supplied: proceeding despite failures.[/yellow]")
    else:
        console.print("\n[green]✓[/green] All gates passed. Ready to export.")
