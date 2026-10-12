"""riskforge risk — risk item management subcommands."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional  # noqa: UP007 — Typer 0.12.3 compat

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Manage risk items: list, accept, mitigate.")
console = Console()


@app.command("list")
def list_risks(
    system_id: str = typer.Argument(..., help="System ID"),
    project_dir: Path = typer.Option(Path("."), "--project-dir"),
    dimension: Optional[str] = typer.Option(None, "--dimension", "-d"),
) -> None:
    """List all risk items for a system."""
    from riskforge.cli.project import open_project, parse_dimension, read_register_or_fail

    dim_filter = parse_dimension(dimension, "'--dimension' / '-d'")
    store = open_project(project_dir)
    register = asyncio.run(read_register_or_fail(store, system_id))

    items = [i for i in register.items if dim_filter is None or i.dimension == dim_filter]

    table = Table(title=f"Risk Items — {system_id}")
    table.add_column("ID", style="dim", max_width=8)
    table.add_column("Dimension")
    table.add_column("Title", max_width=40)
    table.add_column("Score")
    table.add_column("Band")
    table.add_column("Accepted")

    for item in items:
        band_colour = {"low": "green", "medium": "yellow", "high": "orange1", "critical": "red"}
        table.add_row(
            str(item.id)[:8],
            item.dimension.value,
            item.title[:40],
            str(item.risk_score),
            f"[{band_colour.get(item.risk_band, 'white')}]{item.risk_band}[/]",
            "Yes" if item.accepted else "No",
        )

    console.print(table)


@app.command("accept")
def accept_risk(
    system_id: str = typer.Argument(..., help="System ID"),
    risk_id: str = typer.Argument(..., help="Risk item ID (or first 8 chars)"),
    rationale: str = typer.Option(..., "--rationale", "-r", help="Acceptance rationale"),
    project_dir: Path = typer.Option(Path("."), "--project-dir"),
) -> None:
    """Accept a risk item with a documented rationale."""
    from riskforge.cli.errors import fail
    from riskforge.cli.project import open_project, read_register_or_fail
    from riskforge.engine.audit import AuditEngine
    from riskforge.engine.risk import AmbiguousRiskIdError, RiskEngine, RiskNotFoundError
    from riskforge.models.audit import AuditActor

    store = open_project(project_dir)
    asyncio.run(read_register_or_fail(store, system_id))
    actor = AuditActor(type="human", identity="cli")
    audit = AuditEngine(store, actor)
    engine = RiskEngine(store, audit)

    try:
        item = asyncio.run(engine.accept_risk(system_id, risk_id, rationale, "cli"))
    except RiskNotFoundError:
        fail(_no_such_risk(system_id, risk_id))
    except AmbiguousRiskIdError as exc:
        fail(exc.args[0])
    except ValueError as exc:
        fail(str(exc))

    console.print(f"[green]✓[/green] Risk [bold]{str(item.id)[:8]}[/bold] accepted and audited.")


@app.command("mitigate")
def mitigate_risk(
    system_id: str = typer.Argument(..., help="System ID"),
    risk_id: str = typer.Argument(..., help="Risk item ID (or first 8 chars)"),
    description: str = typer.Option(..., "--description", "-m", help="What the control does"),
    control_type: str = typer.Option(
        ..., "--control-type", "-c", help="preventive | detective | corrective"
    ),
    owner: str = typer.Option(..., "--owner", help="Team or person accountable for the control"),
    status: str = typer.Option("planned", "--status", help="planned | implemented | verified"),
    residual_likelihood: Optional[int] = typer.Option(
        None, "--residual-likelihood", min=1, max=5, help="Post-mitigation likelihood (1-5)"
    ),
    residual_severity: Optional[int] = typer.Option(
        None, "--residual-severity", min=1, max=5, help="Post-mitigation severity (1-5)"
    ),
    project_dir: Path = typer.Option(Path("."), "--project-dir"),
) -> None:
    """Add a mitigation to a risk item, optionally re-scoring residual risk."""
    from riskforge.cli.errors import fail
    from riskforge.cli.project import open_project, read_register_or_fail
    from riskforge.engine.audit import AuditEngine
    from riskforge.engine.risk import AmbiguousRiskIdError, RiskEngine, RiskNotFoundError
    from riskforge.models.audit import AuditActor
    from riskforge.models.risk import Mitigation

    if control_type not in ("preventive", "detective", "corrective"):
        raise typer.BadParameter(
            "must be preventive, detective or corrective.", param_hint="'--control-type' / '-c'"
        )
    if status not in ("planned", "implemented", "verified"):
        raise typer.BadParameter(
            "must be planned, implemented or verified.", param_hint="'--status'"
        )

    store = open_project(project_dir)
    asyncio.run(read_register_or_fail(store, system_id))
    actor = AuditActor(type="human", identity="cli")
    audit = AuditEngine(store, actor)
    engine = RiskEngine(store, audit)
    mitigation = Mitigation(
        description=description, control_type=control_type, owner=owner, status=status
    )

    try:
        item = asyncio.run(
            engine.add_mitigation(
                system_id, risk_id, mitigation, residual_likelihood, residual_severity
            )
        )
    except RiskNotFoundError:
        fail(_no_such_risk(system_id, risk_id))
    except AmbiguousRiskIdError as exc:
        fail(exc.args[0])

    vague = " [yellow](flagged vague — replace with a specific control)[/yellow]"
    note = vague if item.mitigations[-1].is_vague else ""
    console.print(
        f"[green]✓[/green] Mitigation added to risk [bold]{str(item.id)[:8]}[/bold].{note} "
        f"Residual: {item.residual_risk_score} ({item.residual_risk_band})."
    )


def _no_such_risk(system_id: str, risk_id: str) -> str:
    return (
        f"No risk item matches id {risk_id} in this register. "
        f"Run `riskforge risk list {system_id}` to see the ids."
    )
