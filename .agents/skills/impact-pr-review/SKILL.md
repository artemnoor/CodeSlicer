---
name: impact-pr-review
description: Review a git diff with Impact Engine, map changed files and symbols to the project graph, calculate impact and risk, and recommend tests. Use for pull requests, staged changes, or requests for a change-impact report.
---

# PR Impact Review

Use the repository's actual diff and graph; do not infer changed symbols from a
commit title.

## Workflow

1. Check `git diff --name-status` and `git diff` without modifying the worktree.
2. Ensure a current graph exists; analyze the project if it is missing or stale.
3. Run:
   `impact-engine --json pr-review <project> --diff-file <diff> --graph <graph.json>`
   or use the configured MCP PR-review operation.
4. Inspect changed files/symbols, risk reasons, confirmed/likely impact,
   unresolved boundaries, and suggested tests.
5. Validate high-risk edges with `explain-edge` and check route/frontend impact.

## Review discipline

- Do not claim a file is affected solely because it shares a name.
- Keep generated, test-only, and documentation-only changes separate.
- Distinguish `must_change` from `should_review`.
- Report missing graph evidence and unsupported language semantics explicitly.
- Do not edit code or commit changes during review.

## Result

Produce a concise PR Impact Report: changed symbols, risk level and reasons,
confirmed impact, likely impact, suspicious/unresolved items, required tests,
recommended tests, and known limitations.
