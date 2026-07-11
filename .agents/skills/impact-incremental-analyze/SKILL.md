---
name: impact-incremental-analyze
description: Reanalyze a changed project incrementally with Impact Engine, reuse unaffected facts, compare the result with a clean rebuild, and diagnose semantic graph differences. Use after leaf or central-service changes when cache reuse and graph equivalence matter.
---

# Incremental Analysis

Incremental reuse is valid only when the semantic graph matches a clean
rebuild.

## Workflow

1. Preserve a clean baseline graph and fingerprint.
2. Apply or inspect the requested change in a disposable working copy.
3. Run `impact-engine --json analyze-incremental <project> ...` with the
   baseline/cache configuration.
4. Record files/facts/nodes/edges reused and rebuilt, invalidated closure,
   resolvers rerun, cache hit rate, and timing.
5. Run a clean full analysis of the same changed copy.
6. Compare core semantic fingerprints first, then full graph fingerprints.
7. If different, list edge/node diffs and provenance instead of widening
   invalidation blindly.

## Quality gates

- `analysis_reused=true` and cache hit rate > 0;
- affected edges rebuilt and unaffected edges reused;
- no dangling or stale edges;
- incremental core semantic fingerprint equals clean rebuild;
- locked benchmark predictions remain unchanged.

## Result

Return before/after metrics, invalidation trace, selective resolver execution,
reuse/speedup, fingerprint equivalence, remaining differences, and limitations.
