# Precision / ranking evaluation

This runner is deterministic and local-only. It analyzes a copied working
tree, writes only a JSON report, and never includes source text in that report.
Missing real corpora are reported as `corpus_unavailable`; no benchmark value
is fabricated.

Run a golden scenario:

```powershell
$env:PYTHONPATH = "src"
python benchmarks/ranking/runner.py --scenario tests/fixtures/review_ranking/synthetic
```

Run an available local corpus:

```powershell
python benchmarks/ranking/runner.py --corpus tests/corpus/JunMate --diff tests/corpus/diffs/jun-change.diff
```

The report includes `top_5_precision`, `top_10_recall`, targeted-test
precision, noise ratio, explanation completeness, actionable-card ratio and a
deterministic time-to-decision proxy. Node/edge count is context only and is
not a quality metric. Absolute quality gates are evaluated independently from
`expected.json` labels and fixed safety thresholds: a current-policy baseline
cannot certify itself. Baselines are read from
`benchmarks/ranking/baseline/`; files without `baseline_kind` are comparative
only and are reported as `ignored_non_independent_baseline`.

The report also records `review_time_seconds` and fails when the configured
maximum is exceeded. Missing expected tests are `not_evaluable`, not a perfect
test-precision score. A corpus with no local project/diff is reported as
`corpus_unavailable`.

Golden `expected.json` fields:

```json
{
  "changed_entities": [],
  "expected_top_5_entities": [],
  "allowed_top_10_entities": [],
  "forbidden_noise_entities": [],
  "expected_tests": [],
  "expected_chain_status": "cross_file_proven",
  "expected_risk": "MEDIUM",
  "expected_confidence": "high",
  "explanation_evidence_requirements": {"minimum_evidence_per_top_result": 1},
  "quality_gates": {
    "min_top_5_precision": 0.8,
    "min_top_10_recall": 0.8,
    "max_noise_ratio": 0.25,
    "max_review_seconds": 30
  }
}
```
