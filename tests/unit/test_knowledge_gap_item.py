"""A question answered unknown says how it was scored (D6 of the 2.0.0 independent test)."""

from __future__ import annotations

from riskforge.engine.assess import DEFAULT_GAP_SCORE, AssessEngine
from riskforge.models.risk import RiskDimension

QUESTION = {"id": "XX-001", "text": "Is it tested?", "guidance": "Guidance.", "article_refs": []}


def _item(**hints: int):
    return AssessEngine().knowledge_gap_item({**QUESTION, **hints}, RiskDimension.robustness)


def test_no_hints_scores_the_default_and_says_so() -> None:
    item = _item()
    assert item.knowledge_gap
    assert (int(item.likelihood), int(item.severity)) == (DEFAULT_GAP_SCORE, DEFAULT_GAP_SCORE)
    assert item.knowledge_gap_reason == (
        "Answered unknown, so the provider has not judged this risk yet. It is scored at "
        "the default, likelihood 3 and severity 3, until it is assessed."
    )


def test_hints_are_used_and_named() -> None:
    item = _item(default_likelihood_hint=2, default_severity_hint=4)
    assert (int(item.likelihood), int(item.severity)) == (2, 4)
    assert "scored at the question's hint, likelihood 2 and severity 4" in item.knowledge_gap_reason


def test_one_hint_names_each_source() -> None:
    item = _item(default_severity_hint=5)
    assert (int(item.likelihood), int(item.severity)) == (3, 5)
    assert (
        "likelihood 3 (the default) and severity 5 (the question's hint)"
        in item.knowledge_gap_reason
    )


def test_an_answered_question_has_no_reason() -> None:
    item = AssessEngine().question_to_risk_item(QUESTION, RiskDimension.robustness, 4, 4)
    assert not item.knowledge_gap
    assert item.knowledge_gap_reason == ""
