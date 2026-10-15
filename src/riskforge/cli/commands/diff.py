"""riskforge diff: compare two risk register snapshots."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

console = Console()

# Free text prints as "text changed"; the full text is in the two files.
TEXT_FIELDS = frozenset(
    {
        "description",
        "acceptance_rationale",
        "knowledge_gap_reason",
        "notes",
        "purpose",
        "deployment_context",
    }
)


def cmd(
    system_id: str = typer.Argument(..., help="System ID"),
    from_export: Path = typer.Argument(..., exists=True, dir_okay=False, help="Baseline rmf.json"),
    to_export: Path = typer.Argument(..., exists=True, dir_okay=False, help="Comparison rmf.json"),
) -> None:
    """Show items added, removed and changed between two exported Risk Management Files."""
    from rich.markup import escape

    from riskforge.cli.errors import fail
    from riskforge.engine.diff import diff_registers, fields_absent_from_schema

    from_data = _load(from_export)
    to_data = _load(to_export)

    for path, data in ((from_export, from_data), (to_export, to_data)):
        system = data["register"].get("system")
        owner = system.get("id") if isinstance(system, dict) else None
        if owner != system_id:
            fail(f"{path} belongs to system {owner}, not {system_id}.")

    ignore = fields_absent_from_schema(from_data.get("rmf_schema_version")) | (
        fields_absent_from_schema(to_data.get("rmf_schema_version"))
    )
    result = diff_registers(from_data["register"], to_data["register"], ignore)
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
        console.print(escape(f"  register {_describe(moved.field, moved.old, moved.new)}"))


def _label(item_id: str, title: object) -> str:
    return f"{item_id[:8]} {str(title or '')[:60]}"


def _value(value: object) -> str:
    if value is None:
        return "not set"
    if isinstance(value, list):
        return ", ".join(_value(entry) for entry in value) or "none"
    if isinstance(value, dict):
        import json

        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return str(value)


def _describe(field: str, old: object, new: object) -> str:
    name = field.rsplit(" ", 1)[-1].rsplit(".", 1)[-1]
    if field.startswith("mitigation ") and field.count(" ") == 1:
        if old is None:
            return f'{field}: added "{str(new or "")[:60]}"'
        if new is None:
            return f'{field}: removed "{str(old)[:60]}"'
    if name in TEXT_FIELDS:
        return f"{field}: text changed"
    if name == "title":
        return f'{field}: "{str(old)[:60]}" -> "{str(new)[:60]}"'
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
    seen: set[str] = set()
    for item in items:
        if item["id"] in seen:
            fail(f"{path} is not a valid RMF file: item {item['id']} appears more than once.")
        seen.add(item["id"])
        mitigations = item.get("mitigations", [])
        if not isinstance(mitigations, list) or not all(
            isinstance(mitigation, dict) for mitigation in mitigations
        ):
            fail(f"{path} is not an RMF file: the mitigations of item {item['id']} are not a list.")
        mitigation_ids = [m["id"] for m in mitigations if isinstance(m.get("id"), str)]
        if len(mitigation_ids) != len(set(mitigation_ids)):
            fail(f"{path} is not a valid RMF file: item {item['id']} repeats a mitigation id.")
    return data
