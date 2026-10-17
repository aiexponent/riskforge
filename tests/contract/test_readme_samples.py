"""The README's examples are real: its samples validate and its commands exist."""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

import click
import riskforge._data as data_pkg
import typer
import yaml
from riskforge.cli.errors import EXIT_FAILED, EXIT_OK, EXIT_TAMPERED, EXIT_USAGE
from riskforge.cli.main import app
from riskforge.engine.assess import AssessEngine
from riskforge.integrity.receipts import receipt_from_document
from riskforge.integrity.rmf import check_rmf_document
from riskforge.models.system import AISystem

REPO = Path(__file__).resolve().parents[2]
README = REPO / "README.md"
USER_GUIDE = REPO / "docs" / "user-guide.md"

# Options a command needs at run time although Typer does not mark them required,
# because they fall back to an environment variable.
NEEDS_BY = (("risk", "accept"), ("risk", "mitigate"))


def readme_commands(path: Path) -> list[list[str]]:
    """Every `riskforge ...` command line in the bash and yaml code blocks of ``path``."""
    return commands_in(path.read_text(encoding="utf-8"))


def commands_in(text: str) -> list[list[str]]:
    """Every `riskforge ...` command line in the bash and yaml code blocks of ``text``."""
    found: list[list[str]] = []
    for _language, block in re.findall(r"```(bash|yaml)\n(.*?)```", text, flags=re.S):
        for line in re.sub(r"\\\n\s*", " ", block).splitlines():
            line = re.sub(r"^-?\s*run:\s*", "", line.split(" #", 1)[0].strip())
            if line.startswith("riskforge "):
                found.append(shlex.split(line)[1:])
    return found


def command_problems(path: Path) -> list[str]:
    """Commands in ``path`` that do not exist, and options those commands do not take."""
    root = typer.main.get_command(app)
    problems: list[str] = []
    for args in readme_commands(path):
        command: click.Command = root
        rest = list(args)
        names: list[str] = []
        while isinstance(command, click.Group) and rest and rest[0] in command.commands:
            names.append(rest[0])
            command = command.commands[rest.pop(0)]
        shown = f"riskforge {' '.join(args)}"
        if isinstance(command, click.Group) and "--help" not in rest:
            problems.append(f"{shown}: no such command")
            continue
        known = {"--help"} | {
            opt for param in command.params for opt in (*param.opts, *param.secondary_opts)
        }
        problems += [
            f"{shown}: unknown option {token}"
            for token in rest
            if token.startswith("-") and token.split("=", 1)[0] not in known
        ]
        if tuple(names) in NEEDS_BY and "--by" not in rest:
            problems.append(f"{shown}: missing --by, which the command requires")
    return problems


def _block(language: str, marker: str) -> str:
    text = README.read_text(encoding="utf-8")
    match = re.search(rf"```{language}\n(.*?)```", text[text.index(marker) :], flags=re.S)
    assert match, marker
    return match.group(1)


def test_every_readme_command_and_flag_exists() -> None:
    assert len(readme_commands(README)) >= 15
    assert command_problems(README) == []


def test_every_user_guide_command_and_flag_exists() -> None:
    assert len(readme_commands(USER_GUIDE)) >= 10
    assert command_problems(USER_GUIDE) == []


def test_quick_start_follows_the_signed_flow() -> None:
    text = README.read_text(encoding="utf-8")
    quick_start = text[text.index("## Quick Start") : text.index("## Why RiskForge")]
    commands = [" ".join(args) for args in commands_in(quick_start)]
    steps = [
        "init",
        "assess",
        "keygen",
        "export",
        "receipt",
        "verify",
        "verify --file",
        "verify --receipt",
    ]
    position = 0
    for step in steps:
        later = [i for i, line in enumerate(commands) if i >= position and line.startswith(step)]
        assert later, f"Quick Start has no `riskforge {step}` after step {position}: {commands}"
        position = later[0] + 1
    assert any("--sign" in line for line in commands if line.startswith("export"))
    assert any("--trusted-key" in line for line in commands if line.startswith("verify --file"))


def test_system_yaml_sample_is_a_real_system_record() -> None:
    data = yaml.safe_load(_block("yaml", "View a starter <code>system.yaml</code>"))
    assert set(data) <= set(AISystem.model_fields)
    AISystem.model_validate(data)


def test_rmf_sample_is_a_real_export_that_verifies() -> None:
    document = json.loads(_block("json", "View an exported <code>rmf.json</code>"))
    assert document["rmf_schema_version"] == "1.1.0"
    assert document["signatures"], "the sample is made with export --sign"
    signer = document["public_keys"][0]["public_key"]
    check = check_rmf_document(
        document,
        trusted_keys=[signer],
        receipts=[("README rmf.json", receipt_from_document(document))],
    )
    assert check.ok, check.findings
    assert check.schema_errors == []


def test_rmf_sample_matches_the_system_yaml_sample() -> None:
    system = yaml.safe_load(_block("yaml", "View a starter <code>system.yaml</code>"))
    document = json.loads(_block("json", "View an exported <code>rmf.json</code>"))
    assert document["register"]["system"]["id"] == system["id"]


def test_exit_code_table_matches_the_cli() -> None:
    text = README.read_text(encoding="utf-8")
    section = text[text.index("### Exit Code Contract") : text.index("## CLI Command Reference")]
    codes = {int(code) for code in re.findall(r"^\| `(\d)` \|", section, flags=re.M)}
    assert codes == {EXIT_OK, EXIT_FAILED, EXIT_TAMPERED, EXIT_USAGE}


def test_user_guide_exit_code_table_matches_the_cli() -> None:
    text = USER_GUIDE.read_text(encoding="utf-8")
    section = text[
        text.index("## Exit codes (for CI)") : text.index("## Continuous integration recipe")
    ]
    codes = {int(code) for code in re.findall(r"^\| (\d) \|", section, flags=re.M)}
    assert codes == {EXIT_OK, EXIT_FAILED, EXIT_TAMPERED, EXIT_USAGE}


def test_pattern_claim_matches_the_bundled_patterns() -> None:
    text = " ".join(README.read_text(encoding="utf-8").split())
    patterns = AssessEngine(Path(data_pkg.__file__).parent).load_patterns()
    claimed = re.search(r"(\d+) pre-built risk patterns", text)
    assert claimed, "README states how many risk patterns ship"
    assert int(claimed.group(1)) == len(patterns)
    for pattern in patterns:
        if pattern.get("high_risk_route") == "annex_i":
            assert "Art. 6(1)" in text, pattern["pattern_id"]
        else:
            assert f"({pattern['annex_iii_point']})" in text, pattern["pattern_id"]
