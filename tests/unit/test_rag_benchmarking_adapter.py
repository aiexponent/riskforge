"""The rag-benchmarking adapter reads what rag-benchmarking writes (PRD-330)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from riskforge.adapters.base import AdapterSchemaError
from riskforge.adapters.rag_benchmarking import RAGBenchmarkingAdapter

UPSTREAM = Path(__file__).resolve().parents[1] / "fixtures" / "upstream"


def _load(name: str) -> dict:
    return json.loads((UPSTREAM / name).read_text(encoding="utf-8"))


def test_real_benchmark_report_produces_one_item_per_failing_metric() -> None:
    items = RAGBenchmarkingAdapter().transform(_load("rag_benchmarking_benchmark_report.json"))
    by_title = {item.title: item for item in items}
    assert set(by_title) == {
        "Accuracy below threshold: faithfulness",
        "Accuracy below threshold: answer_relevancy",
    }
    for item in items:
        assert item.source == "rag_benchmarking"
        assert item.source_ref == "rag:riskforge-fixture-001"
        assert (int(item.likelihood), int(item.severity)) == (4, 4)


def test_legacy_1x_report_still_imports() -> None:
    items = RAGBenchmarkingAdapter().transform(_load("sample_rag_benchmarking_report.json"))
    assert {item.title for item in items} == {
        "Accuracy below threshold: faithfulness",
        "Accuracy below threshold: answer_relevancy",
    }
    assert all(item.source_ref == "rag:rag-pipeline-001" for item in items)


def test_nan_in_a_checked_metric_is_refused() -> None:
    report = _load("rag_benchmarking_benchmark_report.json")
    report["metrics"]["faithfulness"] = float("nan")
    with pytest.raises(AdapterSchemaError, match="faithfulness"):
        RAGBenchmarkingAdapter().transform(report)


def test_null_in_a_checked_metric_is_refused() -> None:
    # BenchmarkReport.model_dump_json writes a NaN score as null.
    report = _load("rag_benchmarking_benchmark_report.json")
    report["metrics"]["answer_relevancy"] = None
    with pytest.raises(AdapterSchemaError, match="answer_relevancy"):
        RAGBenchmarkingAdapter().transform(report)


def test_nan_in_an_unchecked_metric_is_ignored() -> None:
    report = _load("rag_benchmarking_benchmark_report.json")
    report["metrics"]["mrr"] = float("nan")
    assert len(RAGBenchmarkingAdapter().transform(report)) == 2


def test_report_without_run_id_or_schema_version_is_refused() -> None:
    with pytest.raises(AdapterSchemaError, match="run_id"):
        RAGBenchmarkingAdapter().transform({"metrics": {"faithfulness": 0.5}})


def test_unknown_major_schema_version_is_refused() -> None:
    with pytest.raises(AdapterSchemaError, match="not supported"):
        RAGBenchmarkingAdapter().transform(
            {"schema_version": "2.0.0", "pipeline_id": "p", "metrics": {}}
        )


def test_both_spellings_of_answer_relevancy_are_refused() -> None:
    # Which value wins would depend on JSON key order, so neither is picked.
    for metrics in (
        {"answer_relevance": 0.9, "answer_relevancy": 0.1},
        {"answer_relevancy": 0.1, "answer_relevance": 0.9},
    ):
        with pytest.raises(AdapterSchemaError, match="answer_relevance.*answer_relevancy"):
            RAGBenchmarkingAdapter().transform({"run_id": "r", "metrics": metrics})


@pytest.mark.parametrize("value", [-0.5, 1.5])
def test_checked_metric_outside_zero_to_one_is_refused(value: float) -> None:
    report = _load("rag_benchmarking_benchmark_report.json")
    report["metrics"]["faithfulness"] = value
    with pytest.raises(AdapterSchemaError, match=rf"faithfulness.*{value}"):
        RAGBenchmarkingAdapter().transform(report)


@pytest.mark.parametrize("value", [0, 1, 0.0, 1.0])
def test_checked_metric_at_the_bounds_is_accepted(value: float) -> None:
    report = _load("rag_benchmarking_benchmark_report.json")
    report["metrics"]["faithfulness"] = value
    RAGBenchmarkingAdapter().transform(report)
