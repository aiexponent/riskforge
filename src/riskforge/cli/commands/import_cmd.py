"""riskforge import: import upstream tool reports into the risk register."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console

if TYPE_CHECKING:
    from riskforge.models.risk import RiskItem
    from riskforge.storage.filesystem import FileStore

console = Console()


def cmd(
    system_id: str = typer.Argument(..., help="System ID"),
    adapter: str = typer.Option(
        ..., "--adapter", "-a", help="Adapter name (e.g. rag-benchmarking)"
    ),
    report: Path = typer.Option(
        ...,
        "--report",
        "-r",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Path to upstream report JSON",
    ),
    project_dir: Path = typer.Option(Path("."), "--project-dir"),
) -> None:
    """Import an upstream tool report and add derived risk items to the register.

    Supported adapters: rag-benchmarking, traceforge
    """
    import json

    from riskforge.adapters.base import AdapterSchemaError
    from riskforge.cli.errors import fail
    from riskforge.cli.project import read_register_or_fail, run_checked
    from riskforge.engine.audit import AuditEngine
    from riskforge.engine.risk import RiskEngine
    from riskforge.models.audit import AuditActor
    from riskforge.plugins.registry import PluginRegistry

    registry = PluginRegistry()
    registry.load_all()
    if adapter not in registry.list_adapters():
        raise typer.BadParameter(
            f"unknown adapter '{adapter}'. Available: {', '.join(registry.list_adapters())}.",
            param_hint="'--adapter' / '-a'",
        )

    async def _import(store: FileStore) -> list[RiskItem]:
        await read_register_or_fail(store, system_id)
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            fail(f"{report} is not a JSON report (it is binary).")
        except json.JSONDecodeError as exc:
            fail(f"{report} is not valid JSON: {exc}")
        try:
            risk_items = registry.get_adapter(adapter).transform(data)
        except AdapterSchemaError as exc:
            fail(f"{report}: {exc}")
        actor = AuditActor(type="human", identity="cli-import")
        engine = RiskEngine(store, AuditEngine(store, actor))
        for item in risk_items:
            await engine.add_risk(system_id, item)
        return risk_items

    risk_items = run_checked(project_dir, _import)
    console.print(
        f"[green]✓[/green] Imported {len(risk_items)} risk item(s) from "
        f"[bold]{adapter}[/bold] report."
    )
