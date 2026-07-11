---
name: impact-runtime-validate
description: Validate static Impact Engine relationships with a real test or runtime trace and report observed evidence without overstating coverage. Use when a static edge needs runtime support, a user asks whether a call really occurs, or a test should confirm an impact chain.
---

# Runtime Validate

Runtime observation strengthens a hypothesis for a scenario; it does not prove
that the relationship always occurs in production.

## Workflow

1. Start from a current graph and choose a bounded entrypoint/test.
2. Run:
   `impact-engine --json runtime-trace <project> --graph <graph.json> -- <test command>`
3. Inspect observed calls, route hits, test identity, environment,
   instrumentation, call count, async/subprocess coverage, and mock detection.
4. Match runtime targets to canonical graph nodes. Keep unmatched events in
   quarantine; do not create confirmed edges manually.
5. Report `runtime_observed`, `not_observed`, `runtime_only_observation`, or
   `static/runtime mismatch` with the scenario context.

## Rules

- `not_observed` is not proof of absence.
- Mocked or incomplete traces cannot promote an edge to trusted.
- Preserve static evidence and runtime evidence as separate observations.
- Report the exact test command and environment.
