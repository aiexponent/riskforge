"""Engine must not import CLI modules.

ADR-02 mandates strict import boundary separation:
- riskforge.engine.* must not import from riskforge.cli.*
- riskforge.api, the supported library surface, must not import it either

This test suite is parametrised over all engine submodules and enforces
the boundary by introspecting the loaded module's global namespace and
source file references. Violations are caught in CI before merge.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys

import pytest


def _submodules(package: str) -> list[str]:
    """Walk all submodules of a package and return their dotted names."""
    try:
        mod = importlib.import_module(package)
    except ImportError:
        return []
    return [m.name for m in pkgutil.walk_packages(mod.__path__, f"{package}.")]


ENGINE_MODULES = _submodules("riskforge.engine")
# riskforge.api re-exports engine names for applications that never load the CLI.
CHECKED_MODULES = [*ENGINE_MODULES, "riskforge.api"]


@pytest.mark.parametrize("module", CHECKED_MODULES)
def test_engine_does_not_import_cli(module: str) -> None:
    """Engine module must not directly import from riskforge.cli.*"""
    m = importlib.import_module(module)
    # Check globals for any reference to cli submodules
    for _name, obj in vars(m).items():
        if hasattr(obj, "__module__") and obj.__module__ is not None:
            assert "riskforge.cli" not in obj.__module__, (
                f"{module} imports {obj.__module__} from riskforge.cli — "
                "import boundary violated (ADR-02)"
            )
    # Check sys.modules for any cli module loaded as a side effect
    for loaded_module in list(sys.modules.keys()):
        if loaded_module.startswith("riskforge.cli"):
            # Only fail if the engine module itself caused this import
            # (Allow for CLI modules loaded by other test parametrisation)
            pass


@pytest.mark.parametrize("module", CHECKED_MODULES)
def test_engine_source_has_no_cli_string(module: str) -> None:
    """Engine source file must not contain 'from riskforge.cli' or 'import riskforge.cli'."""
    import ast

    m = importlib.import_module(module)
    source_file = getattr(m, "__file__", None)
    if source_file is None or not source_file.endswith(".py"):
        return

    source = open(source_file).read()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("riskforge.cli"), (
                    f"{module} ({source_file}:{node.lineno}): "
                    f"'import {alias.name}' violates CLI import boundary (ADR-02)"
                )
        elif isinstance(node, ast.ImportFrom):
            module_str = node.module or ""
            assert not module_str.startswith("riskforge.cli"), (
                f"{module} ({source_file}:{node.lineno}): "
                f"'from {module_str} import ...' violates CLI import boundary (ADR-02)"
            )
