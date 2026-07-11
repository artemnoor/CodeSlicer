---
name: impact-analyze-project
description: Analyze a source repository with Impact Engine and produce a GraphDocument, inventory, diagnostics, and actionable next steps. Use when a user asks to understand a new project, build its dependency graph, inventory languages or libraries, or prepare a project for impact queries.
---

# Analyze Project

Use this workflow to build the baseline graph before answering dependency or
change-impact questions.

## Workflow

1. Identify the project root. Do not include unrelated sibling directories.
2. Run inventory first:
   `impact-engine --json inventory <project>`
3. Run analysis without network or AI research unless explicitly requested.
   Always write the artifact inside the analyzed project so the local UI can
   discover it when started as a separate process:
   `impact-engine --json analyze <project> --no-research-requests --out <project>/.impact_engine/graph.json`
4. Inspect the returned metadata: languages, extractors, parser diagnostics,
   unknown libraries, support-pack errors, quality gates, and graph fingerprint.
5. Report node/edge counts and the supported semantic capability per language.
6. Start the UI with `impact-engine-local-api --default-project <project>`.
   The API automatically loads `<project>/.impact_engine/graph.json`; do not
   claim the UI is ready until `/api/state` returns `has_analysis: true` and
   `/api/graph` returns the same node/edge counts as the CLI result.
7. Keep the GraphDocument path and use it for later `impact`, `explain-edge`,
   and visualization calls.

## Rules

- Prefer installed `impact-engine`; fall back to `python -m impact_engine.cli`.
- Put global `--json` before the subcommand.
- Do not treat unknown regions as proof that no relationship exists.
- Do not claim a library is supported when the output says experimental,
  fallback, ambiguous, or unresolved.
- Do not edit source code during analysis.
- If research is needed, stop after collecting the unknown-library task unless
  the user explicitly authorizes an internet research workflow.

## Result

Return the graph path, inventory summary, extractor status, language
capabilities, unknown-library list, quality warnings, and the exact next command
for an impact query.
