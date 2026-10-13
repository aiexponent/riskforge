# Upstream report fixtures

- `rag_benchmarking_benchmark_report.json`: produced by rag-benchmarking v1.0.2 (commit `642cb54`,
  whose `src/` is identical to `5155fb3`), using its `EvaluationRunner` and
  `BenchmarkReport.model_dump_json`. The Ragas judge needs a networked LLM, so it was replaced
  with fixed faithfulness and answer_relevancy scores. The retrieval metrics (`precision_at_k`,
  `mrr`) are computed by rag-benchmarking. Run id: `riskforge-fixture-001`.
- `sample_rag_benchmarking_report.json`: the older 1.x shape with `schema_version` and
  `pipeline_id`, kept so files written in that shape still import.
- `sample_traceforge_report.json`: TraceForge 1.x shape.
