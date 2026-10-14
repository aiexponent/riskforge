"""riskforge init: initialise a new risk management project."""

from __future__ import annotations

from pathlib import Path
from typing import Optional  # noqa: UP007 (Typer 0.12.3 compat)

import typer
from rich.console import Console

console = Console()


def cmd(
    name: str = typer.Option(..., "--name", "-n", help="AI system name"),
    version: str = typer.Option(..., "--sys-version", "-s", help="AI system version (e.g. '1.0')"),
    purpose: str = typer.Option(..., "--purpose", "-p", help="One-sentence purpose statement"),
    provider: str = typer.Option(..., "--provider", help="Provider organisation name"),
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Annex III category"),
    project_dir: Path = typer.Option(Path("."), "--project-dir", help="Project directory"),
    non_interactive: bool = typer.Option(
        False, "--non-interactive", help="Skip interactive prompts"
    ),
) -> None:
    """Initialise a new RiskForge risk management project.

    Creates .riskforge/ directory, riskforge.yaml manifest, and an initial
    system record with its first audit entry. Run this once per AI system you
    are documenting.
    """
    import asyncio
    import uuid

    from riskforge.cli.errors import fail
    from riskforge.cli.project import parse_category
    from riskforge.engine.audit import AuditEngine
    from riskforge.engine.system import SystemEngine
    from riskforge.models.audit import AuditActor
    from riskforge.models.system import AISystem
    from riskforge.storage.errors import ProjectExistsError
    from riskforge.storage.filesystem import FileStore

    store = FileStore(project_dir)
    project_id = str(uuid.uuid4())

    system = AISystem(
        name=name,
        version=version,
        purpose=purpose,
        provider_name=provider,
        annex_iii_category=parse_category(category),
    )

    async def _init() -> None:
        await store.init_project(
            project_id,
            {"system_name": name, "created_by": "riskforge init"},
        )
        audit = AuditEngine(store, AuditActor(type="human", identity="cli"))
        await SystemEngine(store, audit).create(system)

    try:
        asyncio.run(_init())
    except ProjectExistsError as exc:
        fail(
            f"{exc} Delete .riskforge/ and riskforge.yaml to start again, "
            "or use another --project-dir."
        )

    console.print(f"[green]✓[/green] Initialised RiskForge project: [bold]{name} v{version}[/bold]")
    sid = str(system.id)
    console.print(f"  System ID: [dim]{sid}[/dim]")
    console.print(f"  Project dir: [dim]{project_dir.resolve()}[/dim]")
    console.print("")
    console.print(
        f"Next: [bold]riskforge system classify {sid} --confirm[/bold], "
        f"then [bold]riskforge assess {sid} -a NAME -r ROLE[/bold]"
    )
