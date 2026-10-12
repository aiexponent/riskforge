"""CLI-surface contract: group help must not advertise commands that do not ship.

The risk/system/tests groups previously listed subcommands (risk add/edit/score,
system edit, tests list) that were never implemented, so `--help` was wrong at
runtime. This locks each group's help description to its registered command set:
any command name listed after the colon in the help must actually be registered.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import re

import pytest
from riskforge.cli.commands import risk, system, tests_cmd
from riskforge.cli.main import app as main_app
from typer.testing import CliRunner


def _groups():
    return {"risk": risk.app, "system": system.app, "tests": tests_cmd.app}


def test_group_help_lists_only_registered_commands() -> None:
    for name, app in _groups().items():
        registered = {c.name for c in app.registered_commands}
        help_text = app.info.help or ""
        if ":" not in help_text:
            continue
        listed = re.findall(r"[a-z][a-z_]+", help_text.rsplit(":", 1)[1])
        phantom = [token for token in listed if token not in registered]
        assert not phantom, (
            f"'{name}' group help advertises command(s) that do not ship: {phantom}; "
            f"registered = {sorted(registered)}"
        )


def test_each_group_registers_at_least_one_command() -> None:
    for name, app in _groups().items():
        assert app.registered_commands, f"'{name}' group has no registered commands"


def test_serve_command_is_not_registered() -> None:
    """PRD-354: the experimental `serve` command was removed in 2.0.0."""
    registered = {c.name for c in main_app.registered_commands}
    assert "serve" not in registered

    result = CliRunner().invoke(main_app, ["--help"])
    assert result.exit_code == 0, result.output
    assert not re.search(r"^\W*serve\b", result.output, re.MULTILINE), result.output


def test_server_package_is_not_shipped() -> None:
    """PRD-354: the server package and its install extra were removed in 2.0.0."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("riskforge.server")

    extras = importlib.metadata.metadata("riskforge").get_all("Provides-Extra") or []
    assert "server" not in extras
