"""riskforge tests: test requirement management subcommands."""

from __future__ import annotations

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
    """Derive test requirements from the risk register and save them on it."""
    from riskforge.cli.project import read_register_or_fail, run_checked
    from riskforge.engine.audit import AuditEngine
    from riskforge.engine.risk import RiskEngine
    from riskforge.engine.tests import TestDerivationEngine
    from riskforge.models.audit import AuditActor
    from riskforge.models.requirements import TestRequirement
    from riskforge.storage.filesystem import FileStore

    async def _generate(store: FileStore) -> tuple[list[TestRequirement], bool]:
        register = await read_register_or_fail(store, system_id)
        requirements = TestDerivationEngine().derive(register.items)
        engine = RiskEngine(store, AuditEngine(store, AuditActor(type="human", identity="cli")))
        return requirements, await engine.set_test_requirements(system_id, requirements)

    requirements, changed = run_checked(project_dir, _generate)

    verb = "Saved" if changed else "Unchanged:"
    console.print(
        f"[green]✓[/green] {verb} {len(requirements)} test requirement(s) on the register."
    )
    for req in requirements:
        console.print(
            f"  • [bold]{req.metric_type}[/bold] {req.threshold_range} "
            f"({req.article_ref}), risk {str(req.risk_item_id)[:8]}"
        )
