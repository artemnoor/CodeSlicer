---
name: code-intelligence-orchestrator
description: Routes a code question to CodeSlicer impact analysis, Graphify architecture analysis, or both while preserving evidence boundaries.
---

# Code Intelligence Orchestrator

For a newly received local folder or an explicitly approved Git URL, start with
`impact-engine --json onboard <source> --graphify auto`. A URL requires
`--allow-network`; do not clone, pull, install tools or run tests implicitly.

Use CodeSlicer for change impact, PR risk, targeted tests and evidence paths.
Use Graphify for a separate, high-level architecture graph and communities.
For a cross-cutting question, build or refresh both graphs explicitly and label which result comes from which tool. Do not treat a Graphify edge as canonical CodeSlicer evidence, and do not claim a missing graph is present.

Before reporting a result, check language coverage and diagnostics. Dynamic or unsupported areas must remain `likely` or `unresolved`.
