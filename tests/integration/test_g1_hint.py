"""The command gate G1 tells the user to run exists in the installed CLI (#52)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from rf_testkit import run_rf
from riskforge.engine.validate import ValidateEngine
from riskforge.models.register import RiskRegister
from riskforge.models.risk import Likelihood, RiskDimension, RiskItem, Severity
from riskforge.models.system import AISystem


def test_g1_hint_command_and_options_exist_in_cli_help() -> None:
    now = datetime.now(UTC)
    register = RiskRegister(
        system=AISystem(name="S", version="1", purpose="p", provider_name="P"),
        items=[
            RiskItem(
                dimension=RiskDimension.privacy,
                title="t",
                description="d",
                likelihood=Likelihood(2),
                severity=Severity(2),
                residual_likelihood=Likelihood(2),
                residual_severity=Severity(2),
            )
        ],
        assessor_name="A",
        assessor_role="B",
        assessment_date=now,
        review_date=now + timedelta(days=365),
    )
    g1 = next(r for r in ValidateEngine().run(register) if r.gate_id == "G1")
    command = re.search(r"`(riskforge [^`]+)`", g1.details)
    assert command, g1.details
    words = command.group(1).split()
    subcommand = words[1]

    top = run_rf(["--help"])
    assert top.returncode == 0, top.output
    assert re.search(rf"^\W*{subcommand}\s", top.output, re.MULTILINE), top.output

    sub = run_rf([subcommand, "--help"])
    assert sub.returncode == 0, sub.output
    for option in (w for w in words if w.startswith("-")):
        assert re.search(rf"(?<![\w-]){re.escape(option)}(?![\w-])", sub.output), option
