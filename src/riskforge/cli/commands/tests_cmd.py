"""riskforge tests — test requirement management subcommands."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(help="Derive Article 9(6)–(8) test requirements.")
console = Console()


@app.command("generate")
def generate_tests(
    system_id: str = typer.Argument(..., help="System ID"),
    project_dir: Path = typer.Option(Path("."), "--project-dir"),
) -> None:
    """Derive test requirements from the risk register."""
    from riskforge.cli.project import open_project, read_register_or_fail
    from riskforge.engine.tests import TestDerivationEngine

    store = open_project(project_dir)
    register = asyncio.run(read_register_or_fail(store, system_id))

    engine = TestDerivationEngine()
    requirements = engine.derive(register.items)

    console.print(f"[green]✓[/green] Derived {len(requirements)} test requirement(s).")
    for req in requirements:
        console.print(
            f"  • [bold]{req.metric_type}[/bold] {req.threshold_range} "
            f"({req.article_ref}) — risk {str(req.risk_item_id)[:8]}"
        )
