"""riskforge system: AI system management subcommands."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Optional  # noqa: UP007 (Typer 0.12.3 compat)

import typer
from rich.console import Console

if TYPE_CHECKING:
    from riskforge.storage.filesystem import FileStore

app = typer.Typer(help="Manage the AI system record: show, classify, describe.")
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
    from riskforge.cli.project import cli_actor, parse_category, read_system_or_fail, run_checked
    from riskforge.engine.audit import AuditEngine
    from riskforge.engine.system import SystemEngine

    if not confirm:
        fail(
            "This records the provider's own determination that the system is "
            "high-risk under Annex III (Article 6(2)). Re-run with --confirm to record it."
        )

    cat_enum = parse_category(category)

    async def _classify(store: FileStore) -> None:
        await read_system_or_fail(store, system_id)
        audit = AuditEngine(store, cli_actor())
        await SystemEngine(store, audit).classify(system_id, cat_enum)

    run_checked(project_dir, _classify)
    console.print(
        f"[green]✓[/green] Article 6(2) self-classification recorded for "
        f"[bold]{system_id[:8]}[/bold]. Gate G2 will pass."
    )


@app.command("describe")
def describe_system(
    system_id: str = typer.Argument(..., help="System ID"),
    intended_user: Optional[list[str]] = typer.Option(
        None, "--intended-user", help="Who uses the system's output. Repeatable; replaces the list."
    ),
    input_: Optional[list[str]] = typer.Option(
        None, "--input", help="What the system takes in. Repeatable; replaces the list."
    ),
    output: Optional[list[str]] = typer.Option(
        None, "--output", help="What the system produces. Repeatable; replaces the list."
    ),
    deployment_context: Optional[str] = typer.Option(
        None, "--deployment-context", help="Where and how the system is deployed"
    ),
    provider_contact: Optional[str] = typer.Option(
        None, "--provider-contact", help="Contact for the provider, such as an email address"
    ),
    project_dir: Path = typer.Option(Path("."), "--project-dir"),
) -> None:
    """Set the system description: intended users, inputs, outputs, deployment context, contact.

    Only the options given change. A repeatable option replaces its whole list. The change
    is made to the system record and its register together and recorded in the audit log
    as system.described. Gate G5 warns while any of these fields is empty.

    Exit codes: 0 described or nothing changed, 2 the project failed its integrity check,
    3 no option given, or no project or no such system.
    """
    from riskforge.cli.errors import fail
    from riskforge.cli.project import cli_actor, read_system_or_fail, run_checked
    from riskforge.engine.audit import AuditEngine
    from riskforge.engine.system import SystemEngine

    fields = {
        "intended_users": list(intended_user) if intended_user else None,
        "inputs": list(input_) if input_ else None,
        "outputs": list(output) if output else None,
        "deployment_context": deployment_context,
        "provider_contact": provider_contact,
    }
    if all(value is None for value in fields.values()):
        fail(
            "Give at least one of --intended-user, --input, --output, "
            "--deployment-context or --provider-contact."
        )
    changed: list[str] = []

    async def _describe(store: FileStore) -> None:
        await read_system_or_fail(store, system_id)
        audit = AuditEngine(store, cli_actor())
        _, names = await SystemEngine(store, audit).describe(system_id, **fields)
        changed.extend(names)

    run_checked(project_dir, _describe)
    if changed:
        console.print(
            f"[green]✓[/green] System description updated for [bold]{system_id[:8]}[/bold]: "
            f"{', '.join(changed)}."
        )
    else:
        console.print(f"System description of [bold]{system_id[:8]}[/bold] already matches.")
