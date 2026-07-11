---
name: impact-review-change
description: Determine what a changed file, symbol, route, service, or repository method can affect using an existing Impact Engine graph. Use when the user asks what breaks, what depends on a symbol, or what should be checked after a code change.
---

# Review Change Impact

Use an existing GraphDocument; analyze first if no usable graph exists.

## Workflow

1. Resolve the changed target by exact node ID, then by `--symbol` or `--file`.
2. Run:
   `impact-engine --json impact <graph.json> --symbol <symbol> --direction both --depth 8`
3. Read `confirmed`, `likely`, `suspicious`, `not_resolved`, `impact_ranking`,
   `impact_paths`, and `chain_confidence`.
4. Separate upstream callers from downstream dependencies. Include affected
   routes, tests, services, frontend clients, and external boundaries.
5. Use `explain-edge` for the strongest path and every surprising edge.
6. Recommend tests from confirmed TESTS edges; label inferred suggestions as
   recommended, never as required proof.

## Trust rules

- Never promote a likely or suspicious edge to confirmed in the response.
- A path is only as strong as its weakest evidence status.
- Name similarity alone is not evidence.
- An empty result must include `isolated` and `isolation_reason`.
- Mention unresolved boundaries instead of filling them with guesses.

## Result

Return: changed node, must-change confirmed items, should-review likely items,
suspicious items, unresolved boundaries, best evidence path, chain confidence,
impact score ranking, and suggested tests.
