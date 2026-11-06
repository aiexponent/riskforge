"""Question bank risk titles (D3 of the 2.0.0 independent test).

Risk items made from the bank used to take the question text cut at 120 characters as
their title, often mid-phrase, and phrased as a question, so a score did not say whether
it was for the control being missing or present. Each question now has a ``risk_title``
phrased as the risk, and the item's description keeps the full question.
"""

from __future__ import annotations

import pytest
from riskforge.engine.assess import AssessEngine, question_description, question_risk_title
from riskforge.models.risk import QUESTION_TITLE_MAX_LENGTH, RiskDimension

ENGINE = AssessEngine()
QUESTIONS = [
    pytest.param(question, dimension, id=question["id"])
    for dimension in RiskDimension
    for question in ENGINE.load_questions(dimension)
]


def test_the_bank_has_37_questions() -> None:
    assert len(QUESTIONS) == 37


@pytest.mark.parametrize(("question", "dimension"), QUESTIONS)
def test_every_question_has_a_whole_risk_title_that_is_not_a_question(
    question: dict, dimension: RiskDimension
) -> None:
    title = question.get("risk_title", "")
    assert title, f"{question['id']} has no risk_title"
    assert title == title.strip()
    assert len(title) <= QUESTION_TITLE_MAX_LENGTH
    assert not title.endswith(("?", ".", "..."))
    assert "—" not in title


def test_risk_titles_are_unique() -> None:
    titles = [q.values[0]["risk_title"] for q in QUESTIONS]
    assert len(set(titles)) == len(titles)


@pytest.mark.parametrize(("question", "dimension"), QUESTIONS)
def test_an_item_takes_the_risk_title_and_keeps_the_full_question(
    question: dict, dimension: RiskDimension
) -> None:
    item = ENGINE.question_to_risk_item(question, dimension, 3, 3)
    assert item.title == question["risk_title"]
    assert item.description.startswith(f"Question {question['id']}: {question['text']}")
    assert item.description.endswith(question["guidance"])


def test_a_knowledge_gap_item_takes_the_risk_title_too() -> None:
    question = ENGINE.load_questions(RiskDimension.discrimination)[0]
    item = ENGINE.knowledge_gap_item(question, RiskDimension.discrimination)
    assert item.title == question["risk_title"]


def test_a_question_without_a_risk_title_keeps_the_earlier_title_and_description() -> None:
    question = {"id": "XX-001", "text": "Is it so? " * 20, "guidance": "Guide."}
    assert question_risk_title(question) == question["text"][:QUESTION_TITLE_MAX_LENGTH]
    assert question_description(question) == "Guide."
    assert question_description({"text": "Is it so?"}) == "Is it so?"


def test_a_question_without_an_id_or_guidance_still_describes_itself() -> None:
    question = {"text": "Is it so?", "risk_title": "It is not so"}
    assert question_description(question) == "Question: Is it so?"


@pytest.mark.parametrize(("question", "dimension"), QUESTIONS)
def test_every_hint_is_on_the_1_to_5_scale(question: dict, dimension: RiskDimension) -> None:
    """A hint is null (no hint) or 1 to 5, never 0.

    ``knowledge_gap_item`` reads a falsy hint as no hint, so a 0 would be scored at the
    default instead.
    """
    for name in ("default_likelihood_hint", "default_severity_hint"):
        hint = question.get(name)
        is_score = isinstance(hint, int) and not isinstance(hint, bool)
        assert hint is None or (is_score and 1 <= hint <= 5), question["id"]
