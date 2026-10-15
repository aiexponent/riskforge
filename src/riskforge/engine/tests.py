"""TestDerivationEngine — derives test requirements from risk items."""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from riskforge.models.requirements import TestRequirement
from riskforge.models.risk import RiskDimension, RiskItem

# Dimension → suggested metric types for Art.9(8) test requirements
DIMENSION_METRIC_HINTS: dict[RiskDimension, list[dict[str, str]]] = {
    RiskDimension.robustness: [
        {
            "metric_type": "faithfulness",
            "threshold_range": ">= 0.85",
            "article_ref": "Art.9(8)",
        },
        {
            "metric_type": "answer_relevance",
            "threshold_range": ">= 0.80",
            "article_ref": "Art.9(8)",
        },
    ],
    RiskDimension.discrimination: [
        {
            "metric_type": "demographic_parity",
            "threshold_range": "<= 0.10",
            "article_ref": "Art.9(8)",
        },
        {
            "metric_type": "equalised_odds",
            "threshold_range": "<= 0.10",
            "article_ref": "Art.9(8)",
        },
    ],
    RiskDimension.privacy: [
        {
            "metric_type": "pii_leakage_rate",
            "threshold_range": "= 0.00",
            "article_ref": "Art.9(8)",
        },
    ],
    RiskDimension.transparency: [
        {
            "metric_type": "explanation_coverage",
            "threshold_range": ">= 0.90",
            "article_ref": "Art.13",
        },
    ],
    RiskDimension.human_oversight: [
        {
            "metric_type": "override_latency_ms",
            "threshold_range": "<= 500",
            "article_ref": "Art.14",
        },
    ],
    RiskDimension.health_safety: [
        {
            "metric_type": "false_negative_rate",
            "threshold_range": "<= 0.01",
            "article_ref": "Art.9(2)(b)",
        },
    ],
    RiskDimension.data_governance: [
        {
            "metric_type": "data_quality_score",
            "threshold_range": ">= 0.95",
            "article_ref": "Art.10",
        },
    ],
    RiskDimension.fundamental_rights: [
        {
            "metric_type": "fundamental_rights_impact_score",
            "threshold_range": "= 0",
            "article_ref": "Art.9(2)(a)",
        },
    ],
}


# Requirement ids are uuid5 of the risk item id and metric under this namespace, so the
# same register yields the same ids on every run and machine.
TEST_ID_NAMESPACE = uuid5(NAMESPACE_URL, "https://github.com/aiexponent/riskforge#test-requirement")


class TestDerivationEngine:
    """Derives Article 9(6) to 9(8) test requirements from risk items.

    Knowledge gaps and items scoring 9 or more get one requirement each. Ids are derived
    from the item id and metric, so deriving again yields the same requirements.
    """

    __test__ = False  # not a pytest test class

    def derive(self, items: list[RiskItem]) -> list[TestRequirement]:
        """Generate test requirements for a list of risk items."""
        requirements: list[TestRequirement] = []
        for item in items:
            if not (item.knowledge_gap or item.risk_score >= 9):
                continue
            hints = DIMENSION_METRIC_HINTS.get(item.dimension, [])
            if not hints:
                continue
            hint = hints[0]
            requirements.append(
                TestRequirement(
                    id=uuid5(TEST_ID_NAMESPACE, f"{item.id}:{hint['metric_type']}"),
                    risk_item_id=item.id,
                    description=(
                        f"Validate '{item.title}' via {hint['metric_type']} measurement. "
                        f"Target: {hint['threshold_range']}."
                    ),
                    metric_type=hint["metric_type"],
                    threshold_range=hint["threshold_range"],
                    article_ref=hint["article_ref"],
                )
            )
        return requirements
