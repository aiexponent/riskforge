"""Supply-chain guards: declared dependencies are used, the license scan gates, waivers match."""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

from packaging.requirements import Requirement

REPO = Path(__file__).resolve().parents[2]
# Distribution name to import name, for distributions whose import name is not the
# distribution name with "-" replaced by "_".
IMPORT_NAMES = {"pyyaml": "yaml", "python-dotenv": "dotenv"}


def _imported_top_level_modules() -> set[str]:
    names: set[str] = set()
    for path in (REPO / "src" / "riskforge").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names.add(node.module.split(".")[0])
    return names


def _declared_runtime_dependencies() -> list[str]:
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    return [Requirement(spec).name.lower() for spec in project["dependencies"]]


def test_every_declared_runtime_dependency_is_imported() -> None:
    imported = _imported_top_level_modules()
    unused = [
        name
        for name in _declared_runtime_dependencies()
        if IMPORT_NAMES.get(name, name.replace("-", "_")) not in imported
    ]
    assert unused == [], f"declared but never imported: {unused}"


def test_license_scan_gates_the_build() -> None:
    workflow = (REPO / ".github" / "workflows" / "license-compatibility.yml").read_text(
        encoding="utf-8"
    )
    assert "|| true" not in workflow


def test_release_waives_exactly_what_ci_waives() -> None:
    def waivers(name: str) -> set[str]:
        text = (REPO / ".github" / "workflows" / name).read_text(encoding="utf-8")
        return set(re.findall(r"--ignore-vuln (\S+)", text))

    assert waivers("release.yml") == waivers("ci.yml")
