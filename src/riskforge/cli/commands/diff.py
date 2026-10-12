"""riskforge diff — compare two risk register snapshots."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

console = Console()


def cmd(
    system_id: str = typer.Argument(..., help="System ID"),
    from_export: Path = typer.Argument(..., exists=True, dir_okay=False, help="Baseline rmf.json"),
    to_export: Path = typer.Argument(..., exists=True, dir_okay=False, help="Comparison rmf.json"),
) -> None:
    """Show differences between two exported Risk Management Files."""
    from_data = _load(from_export)
    to_data = _load(to_export)

    from_ids = {i["id"] for i in from_data.get("register", {}).get("items", [])}
    to_ids = {i["id"] for i in to_data.get("register", {}).get("items", [])}

    added = to_ids - from_ids
    removed = from_ids - to_ids

    console.print(f"[green]+{len(added)} added[/green]  [red]-{len(removed)} removed[/red]")

    for item in to_data.get("register", {}).get("items", []):
        if item["id"] in added:
            console.print(f"  [green]+[/green] {item['id'][:8]} {item['title'][:60]}")

    for item in from_data.get("register", {}).get("items", []):
        if item["id"] in removed:
            console.print(f"  [red]-[/red] {item['id'][:8]} {item['title'][:60]}")


def _load(path: Path) -> dict:
    """The parsed RMF at *path*, or exit 3 when it is not a JSON RMF file."""
    import json

    from riskforge.cli.errors import fail

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        fail(f"{path} is not a JSON RMF file.")
    except json.JSONDecodeError as exc:
        fail(f"{path} is not a JSON RMF file: {exc}")
    if not isinstance(data, dict) or "register" not in data:
        fail(f"{path} is not an RMF file: it has no 'register' block.")
    return data
