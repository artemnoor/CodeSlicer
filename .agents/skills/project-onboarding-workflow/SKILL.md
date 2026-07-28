---
name: project-onboarding-workflow
description: Connect a local source project or an explicitly approved Git URL, identify its stack, build separate CodeSlicer impact and Graphify architecture graphs, then guide an agent through architecture exploration, Git impact review and confirmed test execution. Use when starting work on a new repository, onboarding a codebase, or beginning a development task from a project folder or repository URL.
---

# Project Onboarding Workflow

Run `impact-engine --json onboard <local-folder> --graphify auto` for a local project. For a Git URL, require the user's explicit approval and add `--allow-network`.

Use Graphify only for broad architecture exploration. Use the canonical CodeSlicer graph for impact, PR risk, evidence and targeted tests. Before a commit run `impact-engine --json review <project> --run-tests suggested`; it only selects tests. Execute a suggested test only after a developer confirms the command.
