"""The validation block an export records (ADR-05): every gate, and the most severe status."""

from __future__ import annotations

import pytest
from riskforge.engine.export import validation_record
from riskforge.engine.validate import GateResult, GateStatus

P, W, F = GateStatus.PASS, GateStatus.WARN, GateStatus.FAIL


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([P, P, P], "PASS"),
        ([P, W, P], "WARN"),
        ([W, F, P], "FAIL"),
        ([F, W], "FAIL"),
    ],
)
def test_status_is_the_most_severe_gate_status(statuses: list[GateStatus], expected: str) -> None:
    results = [GateResult(f"G{n}", f"Gate {n}", s) for n, s in enumerate(statuses, start=1)]
    assert validation_record(results).status == expected


def test_every_gate_is_kept_in_order_with_its_details() -> None:
    results = [
        GateResult("G1", "First", P),
        GateResult("G2", "Second", F, details="2 risks open"),
    ]
    record = validation_record(results)
    assert [(g.gate_id, g.description, g.status, g.details) for g in record.gates] == [
        ("G1", "First", "PASS", ""),
        ("G2", "Second", "FAIL", "2 risks open"),
    ]
