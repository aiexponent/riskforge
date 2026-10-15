"""TestRequirement: a measurable test derived from a risk item."""

from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class TestRequirement(BaseModel):
    """A measurable test/evaluation requirement derived from a risk item."""

    __test__ = False  # not a pytest test class

    id: UUID = Field(default_factory=uuid4)
    risk_item_id: UUID
    description: str
    metric_type: str  # e.g. "demographic_parity", "faithfulness", "adversarial_accuracy"
    threshold_range: str  # e.g. ">= 0.85", "<= 0.05", "[0.80, 1.00]"
    article_ref: str = ""  # e.g. "Art.9(8)"
    nist_rmf_ref: str = ""  # e.g. "MEASURE 2.5"
