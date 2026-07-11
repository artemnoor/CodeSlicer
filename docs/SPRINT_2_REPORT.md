# Sprint 2: Python Semantic Coverage Expansion

Sprint 2 adds exact top-level function/import resolution, nested-scope lookup,
relative import canonicalization, package `__init__` re-export traversal,
module-alias member calls, return-annotation factory propagation, inherited
method lookup, and `super()` target resolution. All edges retain provenance
and evidence; no name-only fallback was added.

## Acceptance

- 21 Python benchmark fixtures, including one negative-only Protocol multiple
  implementation fixture.
- 29 mutation scenarios.
- Benchmark precision/recall/F1: `1.0 / 1.0 / 1.0`.
- Forbidden violations: `0`.
- Mutation failures: `0`.
- Determinism: three runs per fixture, equal graph fingerprints and coverage.
- Full pytest: `347 passed`.

The negative-only fixture reports `status: no_positive_cases` with null
precision/recall rather than claiming quality from zero TP/FP/FN.

## Self-analysis

The reproducible before/after values are stored in
`benchmarks/self_analysis_before_after.json`. The current repository changed:

| Metric | Before | After | Delta |
| --- | ---: | ---: | ---: |
| resolved_exact | 748 | 821 | +73 |
| resolved_inferred | 813 | 877 | +64 |
| actionable_unresolved | 7960 | 7891 | -69 |
| eligible callsites | 9521 | 9589 | +68 |

## Remaining limitations

Dict/provider call patterns and Protocol/ABC multiple implementations remain
ambiguous or unresolved unless an explicit type/provider evidence chain exists.
Factory return propagation currently covers annotated top-level functions; a
factory returning an unannotated class instance is intentionally not inferred.
