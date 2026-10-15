"""Display of risk titles that the question bank import cut at 120 characters."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from riskforge.exporters.base import display_title
from riskforge.exporters.markdown_exporter import MarkdownExporter
from riskforge.models.register import RiskRegister
from riskforge.models.risk import Likelihood, RiskDimension, RiskItem, Severity
from riskforge.models.rmf import RiskManagementFile
from riskforge.models.system import AISystem


@pytest.mark.parametrize(
    ("title", "shown"),
    [
        ("a" * 120, "a" * 120 + "..."),
        ("a" * 119 + "?", "a" * 119 + "?"),
        ("a" * 119 + ".", "a" * 119 + "."),
        ("a" * 119 + "!", "a" * 119 + "!"),
        ("a" * 119, "a" * 119),
        ("a" * 121, "a" * 121),
        ("Short title", "Short title"),
    ],
)
def test_display_title_marks_only_cut_titles(title: str, shown: str) -> None:
    assert display_title(title) == shown


def test_markdown_shows_a_cut_title_with_an_ellipsis() -> None:
    title = "b" * 120
    register = RiskRegister(
        system=AISystem(name="S", version="1", purpose="P", provider_name="Acme"),
        assessor_name="A",
        assessor_role="R",
        assessment_date=datetime(2026, 1, 1, tzinfo=UTC),
        review_date=datetime(2027, 1, 1, tzinfo=UTC),
        question_bank_version="1.0.0",
        items=[
            RiskItem(
                dimension=RiskDimension.privacy,
                title=title,
                description="D",
                likelihood=Likelihood.likely,
                severity=Severity.major,
                residual_likelihood=Likelihood.likely,
                residual_severity=Severity.major,
            )
        ],
    )
    text = MarkdownExporter().render(RiskManagementFile(register=register)).decode("utf-8")
    assert f"{title}..." in text
