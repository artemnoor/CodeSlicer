# Unknown Regions Layer

The unknown-regions layer is an evidence boundary for code that the current
extractors and resolver cannot explain. It is deliberately universal: it does
not contain FastAPI, React, Python, or project-specific rules.

The analysis pipeline runs:

`extractors -> normalization -> semantic binding/resolver -> quality guard -> unknown-regions report`

It reports unresolved calls, isolated symbols, explicit unresolved/ambiguous
nodes, and suspicious edges. An isolated symbol is a review candidate, not a
claim that the symbol is dead or unused.

Every normal analysis writes the AI handoff file to
`<project>/.impact_engine/unknown_region_tasks.json`. It can also be generated
explicitly with:

`impact-engine unknown-regions <project_path> --json`

The task file is an input contract for an external AI agent. The agent may
return hypotheses, but the host must validate them with a bounded test/runtime
trace before applying them.

The report is lossless, but the AI task queue is intentionally selective. It
keeps suspicious edges and unresolved calls with evidence or an explicit
receiver/DI shape, deduplicates equivalent signatures, excludes unlocated noise
and isolated symbols, and applies a bounded queue size. Excluded regions remain
available in the graph metadata for later diagnostics.

Each region carries a stable fingerprint derived from its kind, file, scope and
normalized call expression. It is used to deduplicate recurring patterns and
track whether a gap was closed or reopened across analyses.

An external AI researcher may receive the generated
`unknown_region_research_requests`, propose deterministic hypotheses, and
attach a bounded test plan. A proposal is not added to the graph merely because
the model produced it. `apply_validated_hypotheses` promotes only an exact
`from/to/kind` or edge-id match in an independent runtime/test trace, using
`RUNTIME_CONFIRMED` provenance. Other proposals remain rejected/unresolved.

This prevents AI hallucinations from entering confirmed impact results. It also
means that “no edge found” never becomes proof that no dependency exists.
