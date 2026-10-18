"""Licence items cite Art.10(2), not Art.10(2)(b).

Art.10(2)(b) names "data collection processes and the origin of data, and in the case
of personal data, the original purpose of the data collection". It fits provenance and
personal-data origin, not licence rights.
"""

from __future__ import annotations

import json
from pathlib import Path

from riskforge.adapters.traceforge import TraceForgeAdapter
from riskforge.engine.assess import AssessEngine
from riskforge.models.risk import RiskDimension

UPSTREAM = Path(__file__).resolve().parents[1] / "fixtures" / "upstream"


def _questions() -> dict[str, dict]:
    questions = AssessEngine().load_questions(RiskDimension.data_governance)
    return {q["id"]: q for q in questions}


def test_licence_review_question_cites_art_10_2_only() -> None:
    assert _questions()["DG-002"]["article_refs"] == ["Art.10(2)"]


def test_provenance_question_keeps_art_10_2_b() -> None:
    assert "Art.10(2)(b)" in _questions()["DG-001"]["article_refs"]


def test_traceforge_licence_item_cites_art_10_2_only() -> None:
    report = json.loads((UPSTREAM / "sample_traceforge_report.json").read_text(encoding="utf-8"))
    by_title = {item.title: item for item in TraceForgeAdapter().transform(report)}
    assert by_title["Dataset license conflicts detected"].article_refs == ["Art.10(2)"]
    pii = [item for item in by_title.values() if item.dimension == RiskDimension.privacy]
    assert pii and all("Art.10(2)(b)" in item.article_refs for item in pii)
