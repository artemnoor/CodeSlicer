---
name: project-onboarding-workflow
description: Connect a local source project or an explicitly approved Git URL, identify its stack, build separate CodeSlicer impact and Graphify architecture graphs, then guide an agent through architecture exploration, Git impact review and confirmed test execution. Use when starting work on a new repository, onboarding a codebase, or beginning a development task from a project folder or repository URL.
---

# Project Onboarding Workflow

Run this workflow before investigating or editing an unfamiliar project.

1. Connect and map the project.

   ```text
   impact-engine --json onboard <local-folder> --graphify auto
   ```

   For a Git URL, only clone after the user explicitly permits network access:

   ```text
   impact-engine --json onboard <git-url> --allow-network --graphify auto
   ```

2. Read the JSON result. Report stack, canonical graph coverage, Graphify
   availability and every limitation. Never treat Graphify nodes or edges as
   canonical CodeSlicer impact evidence.

3. Use the architecture graph for broad questions:

   ```text
   graphify query "<architecture question>" --graph <architecture_graph.graph_path>
   ```

   Use CodeSlicer for exact symbols, causal evidence and risk:

   ```text
   impact-engine --json inspect <project> --entity <entity-id>
   impact-engine --json investigate <project> --entity <entity-id>
   ```

4. Before a commit, inspect the real Git diff without changing it:

   ```text
   impact-engine --json review <project> --run-tests suggested
   ```

   Distinguish confirmed, likely and unresolved results. The review may suggest
   test commands; this mode only selects them and does not execute them. Do
   not run a test, build, clone, package install or external-tool command
   until the developer explicitly confirms it. Then use
   `impact-engine ci <project> --run-tests --test-command <argv...>`.

5. After a confirmed code change, refresh only the changed project state:

   ```text
   impact-engine --json analyze-incremental <project> --changed <file>
   ```

Read [workflow-contract.md](references/workflow-contract.md) when deciding
which graph is allowed to answer a question or how to report partial coverage.
