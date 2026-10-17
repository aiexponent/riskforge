"""No code path writes a register or system record without its audit entry (PRD-331).

Outside ``riskforge.storage``, every ``write_register`` and ``write_system`` call must sit
inside an ``async with ....unit_of_work():`` block that also calls ``....record(...)``, or
``....commit(...)`` for entries built with ``AuditEngine.stage`` (the export's checkpoint),
so the write and the entry that describes it commit together or not at all.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "riskforge"
WRITES = {"write_register", "write_system"}
RECORDS = {"record", "commit"}


def _called_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _is_unit_of_work(with_node: ast.AsyncWith) -> bool:
    return any(_called_name(item.context_expr) == "unit_of_work" for item in with_node.items)


def _violations() -> list[str]:
    found: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        parts = path.relative_to(SRC).parts
        # riskforge.testing is the storage contract suite: it writes without an entry
        # on purpose, to prove a backend discards such a write.
        if "storage" in parts or parts[0] == "testing":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        for node in ast.walk(tree):
            if _called_name(node) not in WRITES:
                continue
            where = f"{path.relative_to(SRC)}:{node.lineno}"
            scope = parents.get(node)
            while scope is not None and not (
                isinstance(scope, ast.AsyncWith) and _is_unit_of_work(scope)
            ):
                scope = parents.get(scope)
            if scope is None:
                found.append(f"{where} writes outside a unit of work")
            elif not any(_called_name(inner) in RECORDS for inner in ast.walk(scope)):
                found.append(f"{where} writes in a unit of work that records no audit entry")
    return found


def test_every_state_write_is_recorded_in_its_unit_of_work() -> None:
    assert _violations() == []


def test_the_check_sees_the_engine_writes() -> None:
    engine_writes = [
        node
        for name in ("engine/risk.py", "engine/system.py")
        for node in ast.walk(ast.parse((SRC / name).read_text(encoding="utf-8")))
        if _called_name(node) in WRITES
    ]
    assert len(engine_writes) >= 7
