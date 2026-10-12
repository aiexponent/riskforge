"""RAGBenchmarkingAdapter: imports accuracy evidence from rag-benchmarking reports."""

from __future__ import annotations

import math
from numbers import Real

from packaging.version import InvalidVersion, Version

from riskforge.adapters.base import AdapterSchemaError
from riskforge.models.risk import Likelihood, RiskDimension, RiskItem, Severity


class RAGBenchmarkingAdapter:
    """Maps rag-benchmarking reports to robustness risk items.

    Reads the ``BenchmarkReport`` that rag-benchmarking's EvaluationRunner returns
    (``run_id`` and ``metrics``, no ``schema_version``) and the older 1.x file shape
    (``schema_version`` and ``pipeline_id``). A checked metric below its threshold
    becomes a robustness risk item scaled by the gap.
    """

    adapter_id = "rag-benchmarking"
    supported_schema_range = "^1.0.0"

    THRESHOLDS = {
        "faithfulness": 0.85,
        "answer_relevancy": 0.80,
        "context_recall": 0.75,
    }
    # 1.x files spelled the Ragas metric this way.
    ALIASES = {"answer_relevance": "answer_relevancy"}

    def validate(self, data: dict) -> None:
        if not isinstance(data, dict):
            raise AdapterSchemaError("A rag-benchmarking report must be a JSON object.")
        if "schema_version" in data:
            version_str = str(data["schema_version"])
            try:
                major = Version(version_str).major
            except InvalidVersion as exc:
                raise AdapterSchemaError(
                    f"schema_version {version_str!r} is not a version."
                ) from exc
            if major != 1:
                raise AdapterSchemaError(
                    f"rag-benchmarking report schema v{version_str} is not supported "
                    "(this adapter reads 1.x files and BenchmarkReport files)."
                )
            if not data.get("pipeline_id"):
                raise AdapterSchemaError("A 1.x rag-benchmarking report needs 'pipeline_id'.")
        elif not data.get("run_id"):
            raise AdapterSchemaError(
                "Not a rag-benchmarking report: expected 'run_id' (BenchmarkReport) "
                "or 'schema_version' (1.x file)."
            )
        metrics = data.get("metrics")
        if not isinstance(metrics, dict):
            raise AdapterSchemaError("The report has no 'metrics' object.")
        for raw_name, value in metrics.items():
            if self.ALIASES.get(raw_name, raw_name) not in self.THRESHOLDS:
                continue
            # BenchmarkReport.model_dump_json writes a NaN score as null.
            if value is None or (isinstance(value, Real) and not math.isfinite(value)):
                shown = "null" if value is None else value
                raise AdapterSchemaError(
                    f"Metric '{raw_name}' is {shown}: the evaluation produced no score. "
                    "Re-run the evaluation or remove the metric from the report."
                )
            if isinstance(value, bool) or not isinstance(value, Real):
                raise AdapterSchemaError(f"Metric '{raw_name}' is not a number: {value!r}.")

    def transform(self, data: dict) -> list[RiskItem]:
        self.validate(data)
        source = data.get("run_id") or data["pipeline_id"]
        metrics = {self.ALIASES.get(name, name): value for name, value in data["metrics"].items()}
        items: list[RiskItem] = []
        for metric_name, threshold in self.THRESHOLDS.items():
            value = metrics.get(metric_name)
            if value is None or value >= threshold:
                continue
            gap = threshold - value
            likelihood = Likelihood.likely if gap > 0.15 else Likelihood.possible
            severity = Severity.major if gap > 0.20 else Severity.moderate
            items.append(
                RiskItem(
                    dimension=RiskDimension.robustness,
                    title=f"Accuracy below threshold: {metric_name}",
                    description=(
                        f"rag-benchmarking reports {metric_name}={value:.3f}, "
                        f"below threshold {threshold}. Run: {source}."
                    ),
                    source="rag_benchmarking",
                    source_ref=f"rag:{source}",
                    likelihood=likelihood,
                    severity=severity,
                    residual_likelihood=likelihood,
                    residual_severity=severity,
                    article_refs=["Art.9(2)(a)", "Art.9(7)", "Art.15"],
                    nist_rmf_ref="MEASURE 2.5",
                    iso42001_ref="Clause A.9",
                )
            )
        return items
