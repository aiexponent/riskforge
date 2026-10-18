"""TraceForgeAdapter — imports data governance evidence from TraceForge reports."""

from __future__ import annotations

from packaging.version import Version

from riskforge.adapters.base import AdapterSchemaError
from riskforge.models.risk import Likelihood, RiskDimension, RiskItem, Severity


class TraceForgeAdapter:
    """Maps TraceForge trace_report.json fields to RiskItems.

    PII detected in training data -> Privacy risk item.
    License conflicts in dataset lineage -> Data Governance risk item.
    """

    adapter_id = "traceforge"
    supported_schema_range = "^1.0.0"

    def validate(self, data: dict) -> None:
        version_str = data.get("schema_version", "0.0.0")
        v = Version(version_str)
        if v.major != 1:
            raise AdapterSchemaError(
                f"TraceForge report schema v{version_str} not supported "
                f"by this adapter (supports ^1.0.0). "
                "Upgrade riskforge or pin TraceForge to v1.x."
            )

    def transform(self, data: dict) -> list[RiskItem]:
        self.validate(data)
        items: list[RiskItem] = []
        lineage_id = data.get("lineage_id", "unknown")
        governance = data.get("dataset_governance", {})

        if governance.get("pii_detected", False):
            pii_fields = governance.get("pii_fields_detected", [])
            items.append(
                RiskItem(
                    dimension=RiskDimension.privacy,
                    title="PII detected in training dataset",
                    description=(
                        f"TraceForge detected PII in training data for lineage {lineage_id}. "
                        f"Fields: {', '.join(pii_fields) or 'unspecified'}. "
                        "Article 10(2)(b) requires data governance to cover the origin of data and, "
                        "for personal data, the original purpose of the data collection."
                    ),
                    source="traceforge",
                    source_ref=f"traceforge:{lineage_id}",
                    likelihood=Likelihood.likely,
                    severity=Severity.major,
                    residual_likelihood=Likelihood.likely,
                    residual_severity=Severity.major,
                    article_refs=["Art.10(2)(b)", "Art.9(2)(a)"],
                    nist_rmf_ref="MEASURE 2.10",
                    iso42001_ref="Annex A.7",
                )
            )

        license_conflicts = data.get("license_conflicts", [])
        if license_conflicts:
            items.append(
                RiskItem(
                    dimension=RiskDimension.data_governance,
                    title="Dataset license conflicts detected",
                    description=(
                        f"TraceForge detected {len(license_conflicts)} license conflict(s) "
                        f"in dataset lineage {lineage_id}. "
                        "Conflicting licenses may restrict lawful use of the training data."
                    ),
                    source="traceforge",
                    source_ref=f"traceforge:{lineage_id}",
                    likelihood=Likelihood.possible,
                    severity=Severity.major,
                    residual_likelihood=Likelihood.possible,
                    residual_severity=Severity.major,
                    article_refs=["Art.10(2)"],
                    nist_rmf_ref="MAP 4.1",
                    iso42001_ref="Annex A.7",
                )
            )

        return items
