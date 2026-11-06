"""The Markdown export lists the test requirements and the change log (usability finding 8).

The 2.0.0 independent test found that the Markdown export carried the same content digest
as the JSON but left out the test requirements and the change log the PDF shows.
"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

from riskforge.exporters.markdown_exporter import MarkdownExporter
from riskforge.models.requirements import TestRequirement

# The test modules are not a package; reuse the PDF tests' sample file.
sys.path.insert(0, str(Path(__file__).parent))
from test_pdf_exporter import _sample_rmf, _with_provenance  # noqa: E402


def _markdown(rmf) -> str:
    return MarkdownExporter().render(rmf).decode("utf-8")


def test_markdown_lists_each_test_requirement() -> None:
    rmf = _with_provenance(_sample_rmf())
    text = _markdown(rmf)
    assert "## Test Requirements" in text
    [requirement] = rmf.test_requirements
    row = (
        f"| `{str(requirement.risk_item_id)[:8]}` | demographic\\_parity | "
        "Statistical parity difference across protected groups. | &lt;= 0.10 | Art.9(8) |"
    )
    assert row in text


def test_markdown_says_when_no_test_requirement_is_saved() -> None:
    text = _markdown(_sample_rmf())
    assert "No test requirements saved. Run `riskforge tests generate`" in text


def test_a_pipe_in_a_cell_cannot_split_the_row() -> None:
    rmf = _sample_rmf()
    rmf.test_requirements = [
        TestRequirement(
            risk_item_id=uuid4(),
            description="a | b",
            metric_type="m",
            threshold_range="t",
            article_ref="Art.9(8)",
        )
    ]
    row = next(line for line in _markdown(rmf).splitlines() if "a \\| b" in line)
    assert row.count(" | ") == 4


def test_markdown_lists_the_change_log_of_the_chain_proof() -> None:
    rmf = _with_provenance(_sample_rmf())
    text = _markdown(rmf)
    assert "## Change Log" in text
    for entry in rmf.chain_proof.entries:
        stamp = entry.timestamp.strftime("%Y-%m-%d %H:%M")
        assert f"| {entry.seq} | {stamp} |" in text


def test_markdown_says_when_there_is_no_chain_proof() -> None:
    assert "This export carries no chain proof." in _markdown(_sample_rmf())


def test_a_change_log_time_with_an_offset_is_shown_in_utc() -> None:
    from datetime import datetime, timedelta, timezone

    rmf = _with_provenance(_sample_rmf())
    entry = rmf.chain_proof.entries[0]
    entry.timestamp = datetime(2026, 11, 6, 12, 30, tzinfo=timezone(timedelta(hours=2)))
    assert f"| {entry.seq} | 2026-11-06 10:30 |" in _markdown(rmf)
