"""TestDerivationEngine — derives test requirements from risk items."""

from __future__ import annotations

from functools import lru_cache
from uuid import NAMESPACE_URL, uuid5

from riskforge.models.requirements import TestRequirement
from riskforge.models.risk import RiskDimension, RiskItem

# Every requirement cites Art.9(8): testing against prior defined metrics and probabilistic
# thresholds appropriate to the intended purpose. The provider sets the threshold.
TEST_ARTICLE_REF = "Art.9(8)"
THRESHOLD_SET_BY_PROVIDER = "set by the provider before testing"

# The metric for an item with no question of its own, such as a pattern item, by dimension.
DIMENSION_METRIC_HINTS: dict[RiskDimension, dict[str, str]] = {
    RiskDimension.robustness: {
        "metric_type": "stress_set_accuracy",
        "measure": "Accuracy on a held-out set of edge-case, out-of-distribution and "
        "perturbed inputs",
    },
    RiskDimension.discrimination: {
        "metric_type": "demographic_parity_gap",
        "measure": "Largest difference in positive-outcome rate between protected groups",
    },
    RiskDimension.privacy: {
        "metric_type": "personal_data_exposure_rate",
        "measure": "Share of sampled records, logs and outputs that expose personal data "
        "the purpose does not need",
    },
    RiskDimension.transparency: {
        "metric_type": "explanation_request_fulfilment",
        "measure": "Share of explanation requests answered with the decision logic "
        "within the set time",
    },
    RiskDimension.human_oversight: {
        "metric_type": "override_success_rate",
        "measure": "Share of test overrides that stop or change the output in real time",
    },
    RiskDimension.health_safety: {
        "metric_type": "harmful_failure_rate",
        "measure": "Rate of incorrect outputs or outages in safety-critical test scenarios",
    },
    RiskDimension.data_governance: {
        "metric_type": "data_quality_check_pass_rate",
        "measure": "Share of completeness, consistency and accuracy checks passed "
        "before training",
    },
    RiskDimension.fundamental_rights: {
        "metric_type": "adverse_decision_rate_gap",
        "measure": "Largest difference in adverse-decision rate between groups of "
        "affected people",
    },
}


@lru_cache(maxsize=1)
def question_metrics() -> dict[str, dict[str, str]]:
    """The suggested test metric of each bundled bank question, by question id."""
    from riskforge.engine.assess import AssessEngine

    return {
        question["id"]: {
            "metric_type": question["test_metric_type"],
            "measure": question["test_measure"],
        }
        for questions in AssessEngine().load_all_questions().values()
        for question in questions
        if question.get("test_metric_type") and question.get("test_measure")
    }


def metric_for(item: RiskItem) -> dict[str, str] | None:
    """The metric of the bank question that made ``item``, or of its dimension."""
    if item.source == "question_bank":
        for tag in item.tags:
            if tag in question_metrics():
                return question_metrics()[tag]
    return DIMENSION_METRIC_HINTS.get(item.dimension)


# Requirement ids are uuid5 of the risk item id and metric under this namespace, so the
# same register yields the same ids on every run and machine.
TEST_ID_NAMESPACE = uuid5(NAMESPACE_URL, "https://github.com/aiexponent/riskforge#test-requirement")


def _sentence(text: str) -> str:
    """``text`` ending in a full stop, unless it already ends a sentence."""
    text = text.strip()
    return text if text.endswith((".", "?", "!")) else f"{text}."


class TestDerivationEngine:
    """Derives Article 9(6) to 9(8) test requirements from risk items.

    Knowledge gaps and items scoring 9 or more get one requirement each, with the metric
    of the bank question that made the item, or of its dimension for any other item. The
    threshold is the provider's to set. Ids are derived from the item id and metric, so
    deriving again yields the same requirements.
    """

    __test__ = False  # not a pytest test class

    def derive(self, items: list[RiskItem]) -> list[TestRequirement]:
        """Generate test requirements for a list of risk items."""
        requirements: list[TestRequirement] = []
        for item in items:
            if not (item.knowledge_gap or item.risk_score >= 9):
                continue
            metric = metric_for(item)
            if metric is None:
                continue
            requirements.append(
                TestRequirement(
                    id=uuid5(TEST_ID_NAMESPACE, f"{item.id}:{metric['metric_type']}"),
                    risk_item_id=item.id,
                    description=(
                        f"Risk: {_sentence(item.title)} Measure: {metric['measure']}. Set the "
                        "threshold before testing, appropriate to the intended purpose."
                    ),
                    metric_type=metric["metric_type"],
                    threshold_range=THRESHOLD_SET_BY_PROVIDER,
                    article_ref=TEST_ARTICLE_REF,
                )
            )
        return requirements
