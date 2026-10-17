"""The README's examples are real: its samples validate and its commands exist."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from pathlib import Path

import click
import pytest
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


# Fenced blocks that hold shell commands or CI config. Unlabelled blocks are included
# because some docs show commands without a language tag.
COMMAND_FENCES = {"", "bash", "sh", "shell", "console", "yaml", "yml"}
FENCE = re.compile(r"^```(\w*)[^\n]*\n(.*?)^```", flags=re.S | re.M)
INLINE = re.compile(r"`(riskforge [^`\n]+)`")
# Placeholders stand for a value the reader fills in: `<id>`, `[--strict]`, `...`.
PLACEHOLDER = re.compile(r"<[^<>\n]*>|[\[\]]|\.\.\.")
# Options the root command takes besides --help.
ROOT_OPTIONS = {"--version"}


def readme_commands(path: Path) -> list[list[str]]:
    """Every `riskforge ...` command line in ``path``: code blocks and inline code."""
    return commands_in(path.read_text(encoding="utf-8"))


def _split(line: str) -> list[str]:
    try:
        return shlex.split(PLACEHOLDER.sub(" ", line))[1:]
    except ValueError:
        # An unbalanced quote: keep the tokens so the check still sees the options.
        return PLACEHOLDER.sub(" ", line).split()[1:]


def commands_in(text: str) -> list[list[str]]:
    """Every `riskforge ...` command in ``text``.

    Reads command lines in shell and YAML code blocks (including commented-out
    ``# riskforge ...`` lines and ``run:`` steps) and backticked ``riskforge ...`` spans
    in the prose, tables included.
    """
    found: list[list[str]] = []
    for language, block in FENCE.findall(text):
        if language not in COMMAND_FENCES:
            continue
        for line in re.sub(r"\\\n\s*", " ", block).splitlines():
            line = re.sub(r"^#\s*(?=riskforge )", "", line.strip())
            line = re.sub(r"^(\$\s*|-?\s*run:\s*)", "", line.split(" #", 1)[0].strip())
            if line.startswith("riskforge "):
                found.append(_split(line))
    prose = FENCE.sub("", text)
    found += [_split(span) for span in INLINE.findall(prose)]
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
        if isinstance(command, click.Group):
            # A bare group (`riskforge risk`) names the commands under it.
            allowed = {"--help"} | (ROOT_OPTIONS if command is root else set())
            if (names or rest) and not set(rest) <= allowed:
                problems.append(f"{shown}: no such command")
            continue
        known = {"--help"} | {
            opt for param in command.params for opt in (*param.opts, *param.secondary_opts)
        }
        problems += [
            f"{shown}: unknown option {token}"
            for token in rest
            if token.startswith("-") and token != "-" and token.split("=", 1)[0] not in known
        ]
        if tuple(names) in NEEDS_BY and rest and "--by" not in rest:
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


PUBLIC_DOCS = [
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "docs/",
    "examples/README.md",
    "benchmarks/README.md",
]


def _public_docs() -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", *PUBLIC_DOCS],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line for line in out.splitlines() if line.endswith(".md")]


def test_public_docs_are_listed() -> None:
    assert {"README.md", "docs/user-guide.md", "docs/contributing/add-exporter.md"} <= set(
        _public_docs()
    )


@pytest.mark.parametrize("doc", _public_docs())
def test_every_public_doc_command_and_flag_exists(doc: str) -> None:
    assert command_problems(REPO / doc) == []


@pytest.mark.parametrize(
    "text",
    [
        "| `riskforge compare <id> OLD.json NEW.json` | Show changes. |",
        "Run `riskforge keygen --out KEY` first.",
        "| `riskforge risk lst <id>` | List the risks. |",
        "```bash\n# riskforge verify --strictly\n```\n",
        "```\nriskforge export --system-id <id>\n```\n",
        "```yaml\n- run: riskforge verify --strict-mode\n```\n",
    ],
)
def test_command_check_catches_drift(tmp_path: Path, text: str) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text(text, encoding="utf-8")
    assert command_problems(doc), text


@pytest.mark.parametrize(
    "text",
    [
        "Print it with `riskforge --version`.",
        "The `riskforge risk` commands change the register.",
        "Run `riskforge risk accept <id> <risk-id> --by NAME`.",
        "Run `riskforge verify [--strict]`.",
        "```python\nriskforge = 1\n```\n",
    ],
)
def test_command_check_accepts_real_commands(tmp_path: Path, text: str) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text(text, encoding="utf-8")
    assert command_problems(doc) == []


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
