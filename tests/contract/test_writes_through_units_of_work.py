"""No code path writes a register or system record without its audit entry (PRD-331).

Outside ``riskforge.storage``, every ``write_register`` and ``write_system`` call must sit
inside an ``async with ....unit_of_work():`` block that also calls ``....record(...)``, or
``....commit(...)`` for entries built with ``AuditEngine.stage`` (the export's checkpoint),
so the write and the entry that describes it commit together or not at all. A write in a
nested unit of work counts as recorded when any unit of work around it records.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "riskforge"
WRITES = {"write_register", "write_system"}
RECORDS = {"record", "commit"}

# The storage contract writes without an entry on purpose, to prove a backend discards such
# a write. Only these functions may do so.
UNRECORDED_ON_PURPOSE = {
    ("testing/storage_contract.py", "test_a_change_without_an_entry_is_discarded"),
    ("testing/storage_contract.py", "test_a_change_without_an_entry_is_discarded_on_a_clean_exit"),
}


def _called_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _is_unit_of_work(node: ast.AST) -> bool:
    return isinstance(node, ast.AsyncWith) and any(
        _called_name(item.context_expr) == "unit_of_work" for item in node.items
    )


def _violations_in(tree: ast.AST, where: str) -> list[str]:
    found: list[str] = []
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    for node in ast.walk(tree):
        if _called_name(node) not in WRITES:
            continue
        enclosing = []
        function = None
        scope = parents.get(node)
        while scope is not None:
            if _is_unit_of_work(scope):
                enclosing.append(scope)
            if function is None and isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef):
                function = scope.name
            scope = parents.get(scope)
        if (where, function) in UNRECORDED_ON_PURPOSE:
            continue
        line = f"{where}:{node.lineno}"
        if not enclosing:
            found.append(f"{line} writes outside a unit of work")
        elif not any(
            _called_name(inner) in RECORDS for unit in enclosing for inner in ast.walk(unit)
        ):
            found.append(f"{line} writes in a unit of work that records no audit entry")
    return found


def _violations() -> list[str]:
    found: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(SRC)
        if "storage" in relative.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found.extend(_violations_in(tree, relative.as_posix()))
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


def _scan(code: str, where: str = "testing/storage_contract.py") -> list[str]:
    return _violations_in(ast.parse(textwrap.dedent(code)), where)


def test_a_write_in_a_nested_unit_of_work_counts_when_the_outer_one_records() -> None:
    code = """
        async def change(audit, storage):
            async with audit.unit_of_work():
                async with storage.unit_of_work():
                    await storage.write_register("s", register)
                await audit.record("risk_item.created", "s", {})
        """
    assert _scan(code) == []


def test_an_unrecorded_write_in_the_contract_is_flagged_outside_the_allowlist() -> None:
    code = """
        async def {name}(audit, storage):
            async with audit.unit_of_work():
                await storage.write_register("s", register)
        """
    assert _scan(code.format(name="test_something_else")) == [
        "testing/storage_contract.py:4 writes in a unit of work that records no audit entry"
    ]
    assert _scan(code.format(name="test_a_change_without_an_entry_is_discarded")) == []
    assert _scan(
        code.format(name="test_a_change_without_an_entry_is_discarded"), "engine/risk.py"
    ) == ["engine/risk.py:4 writes in a unit of work that records no audit entry"]


def test_the_allowlisted_functions_exist_and_write() -> None:
    tree = ast.parse((SRC / "testing" / "storage_contract.py").read_text(encoding="utf-8"))
    writers = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and any(_called_name(inner) in WRITES for inner in ast.walk(node))
    }
    assert {name for _path, name in UNRECORDED_ON_PURPOSE} <= writers
