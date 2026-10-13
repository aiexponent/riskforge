"""riskforge system: AI system management subcommands."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional  # noqa: UP007 (Typer 0.12.3 compat)

import typer
from rich.console import Console

app = typer.Typer(help="Manage the AI system record: show, classify.")
console = Console()


@app.command("show")
def show_system(
    system_id: str = typer.Argument(..., help="System ID"),
    project_dir: Path = typer.Option(Path("."), "--project-dir"),
) -> None:
    """Show the AI system metadata."""
    import json

    from rich import print_json

    from riskforge.cli.project import open_project, read_system_or_fail

    store = open_project(project_dir)
    system = asyncio.run(read_system_or_fail(store, system_id))
    print_json(json.dumps(system.model_dump(mode="json"), indent=2))


@app.command("classify")
def classify_system(
    system_id: str = typer.Argument(..., help="System ID"),
    confirm: bool = typer.Option(
        False, "--confirm", help="Confirm the provider's Article 6(2) Annex III self-classification"
    ),
    category: Optional[str] = typer.Option(
        None, "--category", "-c", help="Annex III category to record (optional)"
    ),
    project_dir: Path = typer.Option(Path("."), "--project-dir"),
) -> None:
    """Record the provider's Article 6(2) Annex III self-classification (clears gate G2).

    The provider, not the tool, decides whether a system is high-risk under Annex III.
    This records that determination and writes an audit entry. Re-run with --confirm.
    """
    from riskforge.cli.errors import fail
    from riskforge.cli.project import open_project, parse_category, read_system_or_fail
    from riskforge.engine.audit import AuditEngine
    from riskforge.models.audit import AuditActor

    if not confirm:
        fail(
            "This records the provider's own determination that the system is "
            "high-risk under Annex III (Article 6(2)). Re-run with --confirm to record it."
        )

    cat_enum = parse_category(category)
    store = open_project(project_dir)

    async def _run() -> None:
        system = await read_system_or_fail(store, system_id)

        system.annex_iii_self_classification_documented = True
        if cat_enum is not None:
            system.annex_iii_category = cat_enum
        await store.write_system(system_id, system)

        # Keep the register's embedded system in sync: validate reads it, not system.yaml.
        try:
            register = await store.read_register(system_id)
        except FileNotFoundError:
            register = None
        if register is not None:
            register.system.annex_iii_self_classification_documented = True
            if cat_enum is not None:
                register.system.annex_iii_category = cat_enum
            await store.write_register(system_id, register)

        recorded_category = cat_enum or system.annex_iii_category
        audit = AuditEngine(store, AuditActor(type="human", identity="cli"))
        await audit.record(
            "system.classified",
            system_id,
            {
                "annex_iii_self_classification_documented": True,
                "annex_iii_category": recorded_category.value if recorded_category else None,
            },
        )

    asyncio.run(_run())
    console.print(
        f"[green]✓[/green] Article 6(2) self-classification recorded for "
        f"[bold]{system_id[:8]}[/bold]. Gate G2 will pass."
    )
