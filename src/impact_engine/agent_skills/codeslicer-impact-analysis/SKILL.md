---
name: codeslicer-impact-analysis
description: Evidence-gated static impact analysis, PR review, targeted test selection and explainable paths.
---

# CodeSlicer Impact Analysis

Build or refresh a graph with `impact-engine analyze <project> --use-scan-plan` when it is missing or stale. Query impact using `impact-engine impact <graph.json> --symbol "<symbol>" --direction both` or MCP tool `impact_query`.

For a diff use `impact-engine pr-review <project> --graph <graph.json> --diff-file <diff.patch>` or MCP tool `pr_review`. Report evidence, confidence and coverage. `confirmed`, `likely` and `unresolved` are distinct outcomes; never describe a likely dynamic relationship as confirmed.
