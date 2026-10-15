"""riskforge diff: compare two risk register snapshots."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

console = Console()

TEXT_FIELDS = ("description", "acceptance_rationale")


def cmd(
    system_id: str = typer.Argument(..., help="System ID"),
    from_export: Path = typer.Argument(..., exists=True, dir_okay=False, help="Baseline rmf.json"),
    to_export: Path = typer.Argument(..., exists=True, dir_okay=False, help="Comparison rmf.json"),
) -> None:
    """Show items added, removed and changed between two exported Risk Management Files."""
    from rich.markup import escape

    from riskforge.cli.errors import fail
    from riskforge.engine.diff import diff_registers

    from_data = _load(from_export)
    to_data = _load(to_export)

    for path, data in ((from_export, from_data), (to_export, to_data)):
        system = data["register"].get("system")
        owner = system.get("id") if isinstance(system, dict) else None
        if owner != system_id:
            fail(f"{path} belongs to system {owner}, not {system_id}.")

    result = diff_registers(from_data["register"], to_data["register"])
    console.print(
        f"[green]+{len(result.added)} added[/green]  [red]-{len(result.removed)} removed[/red]  "
        f"[yellow]~{len(result.changed)} changed[/yellow]"
    )
    for item in result.added:
        console.print(f"  [green]+[/green] {escape(_label(item['id'], item.get('title')))}")
    for item in result.removed:
        console.print(f"  [red]-[/red] {escape(_label(item['id'], item.get('title')))}")
    for change in result.changed:
        console.print(f"  [yellow]~[/yellow] {escape(_label(change.item_id, change.title))}")
        for moved in change.changes:
            console.print(escape(f"      {_describe(moved.field, moved.old, moved.new)}"))
    for moved in result.register_changes:
        console.print(
            escape(f"  register {moved.field}: {_value(moved.old)} -> {_value(moved.new)}")
        )


def _label(item_id: str, title: object) -> str:
    return f"{item_id[:8]} {str(title or '')[:60]}"


def _value(value: object) -> str:
    return "not set" if value is None else str(value)


def _describe(field: str, old: object, new: object) -> str:
    if field in TEXT_FIELDS:
        return f"{field}: text changed"
    if field == "title":
        return f'title: "{str(old)[:60]}" -> "{str(new)[:60]}"'
    if field == "mitigations" and old == new:
        return f"mitigations: {old} -> {new}, edited"
    return f"{field}: {_value(old)} -> {_value(new)}"


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
    if not isinstance(data, dict) or not isinstance(data.get("register"), dict):
        fail(f"{path} is not an RMF file: it has no 'register' block.")
    items = data["register"].get("items", [])
    if not isinstance(items, list) or not all(
        isinstance(item, dict) and isinstance(item.get("id"), str) for item in items
    ):
        fail(f"{path} is not an RMF file: its register items are not a list of items with ids.")
    return data
