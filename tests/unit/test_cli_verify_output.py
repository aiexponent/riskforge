"""`riskforge verify` success output must stay free of em-dashes (site content check)."""

from __future__ import annotations

from pathlib import Path

import pytest
from riskforge.cli.main import app
from typer.testing import CliRunner


@pytest.mark.enable_socket  # asyncio.run() opens a loop socketpair
def test_verify_success_message_has_no_em_dash(tmp_path: Path) -> None:
    runner = CliRunner()
    project_dir = str(tmp_path)
    init = runner.invoke(
        app,
        [
            "init",
            "--name",
            "Verify Test System",
            "--sys-version",
            "1.0",
            "--purpose",
            "CLI output test.",
            "--provider",
            "AI Exponent LLC",
            "--category",
            "employment",
            "--project-dir",
            project_dir,
        ],
    )
    assert init.exit_code == 0, init.output

    result = runner.invoke(app, ["verify", "--project-dir", project_dir])

    assert result.exit_code == 0, result.output
    assert "Audit chain verified: no tampering detected." in result.output
    assert "—" not in result.output
