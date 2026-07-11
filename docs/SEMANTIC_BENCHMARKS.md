# Semantic Precision Benchmarks

Each benchmark manifest declares a project, language, resolver rules, an
explicit semantic edge scope, expected edges and forbidden edges. The runner
reports TP/FP/FN, precision, recall, F1 and a graph fingerprint. Structural
edges outside the declared scope are not silently counted as false positives.
Forbidden edges are critical: an unresolved edge is preferable to a false
positive.

Run:

`impact-engine benchmark run benchmarks`

This writes `benchmarks/benchmark_summary.json` and
`benchmarks/determinism_report.json`.

Mutation testing:

`impact-engine benchmark mutate benchmarks`

This writes `benchmarks/mutation_report.json`. Mutations are applied only to
temporary copies of fixtures. Supported operations are
`remove_binding`, `replace_provider`, `add_second_candidate`, `rename_alias`,
`remove_import`, and `change_receiver_type`. A mutation passes only when its
declared graph change checks pass.

Determinism:

`impact-engine benchmark determinism examples/golden_cases/python_di_basic`

The current set contains nine Python fixtures and ten mutation scenarios. It
is a precision baseline, not a claim of complete Python or polyglot semantic
coverage. Direct/imported function fixtures intentionally remain negative
coverage until a resolver rule can prove those calls without name-only
matching. The quality gates are forbidden violations = 0, precision >= 0.95,
determinism = true, positive-support rules have TP > 0, and mutation failures
= 0. Rule groups without positive cases report `precision: null`,
`recall: null`, and `status: no_positive_cases`.
