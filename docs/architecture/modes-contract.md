# CodeSlicer modes contract

CodeSlicer exposes four product modes over one local `GraphDocument`:

```text
review → inspect → investigate → ci
```

`review` is the bounded daily projection of the current Git diff. `inspect`
explains one resolved entity. `investigate` is an explicit bounded deep
traversal. `ci` evaluates the same review projection against an optional
versioned policy. Ranking, traversal, test selection, edge quality and
runtime validation remain shared core services; modes do not implement their
own analyzers.

## Envelope

New mode responses use `CodeSlicerModeReport/v1` and carry:

- `mode`, `status`, `local_only: true`;
- `graph_freshness`, `coverage`, `warnings`;
- `mode_contract.contract_version: CodeSlicerModeContract/v1`;
- evidence-bearing claims with edge `source`, `confidence` and `evidence`;
- `actions.items`, using `CodeSlicerAction/v1`.

Legacy `review` keeps `schema_version: ReviewReport/v1` for old JSON consumers
and adds the common envelope and structured actions additively. Status is
never inferred from an absent field: `ambiguous`/`needs_selection`, `stale`,
`incomplete`, `unsupported` and `analysis_failed` are explicit states or
warnings.

## Mode behavior

### review

```powershell
impact-engine review . --max-results 10 --json
impact-engine review . --scope backend --max-results 10 --json
```

The default is concise top-10, risk, targeted tests and a small set of
evidence-backed chains. Assignments, built-ins, external libraries and
generated/vendor files stay out of concise cards. `--deep` is a compatibility
entry point for an explicit investigation action.

### inspect

```powershell
impact-engine inspect . --entity "Cruxa.Api.Features.Routes.RoutesController.Create" --json
```

Exact IDs win. An ambiguous symbol returns `status=needs_selection` and
`candidates`; the engine never silently picks one. The response includes
compact direct upstream/downstream edges, linked tests/routes, coverage,
provenance and an action to investigate.

### investigate

```powershell
impact-engine investigate . --entity "route:httpget:api/orders" --direction downstream --depth 8 --json
impact-engine investigate . --entity "..." --runtime-validate --json
```

Deep traversal is bounded by depth, node and edge budgets. The response always
returns `truncated`, `max_depth`, `visited_nodes` and `visited_edges` (plus
truncation reasons), graph quality diagnostics and unresolved/suspicious
regions. Runtime validation is never run unless `--runtime-validate` (or the
equivalent API/MCP flag) is explicit.

### ci

```powershell
impact-engine ci . --base origin/main --format json --out .impact_engine/ci-report.json
impact-engine ci . --policy .impact_engine/policy.json --format sarif --out results.sarif
```

The default policy is advisory/non-blocking. Policy files use
`CodeSlicerCIPolicy/v1` and can set `fail_on_risk`,
`fail_on_incomplete_coverage`, `fail_on_stale_graph`,
`require_evidence_for_top_impacts`, `max_noise_ratio`, `max_review_seconds`
and `required_test_status`. CI does not run tests or perform network actions
unless `--run-tests` is explicit. Exit codes are:

```text
0 passed or advisory findings only
1 policy violation
2 invalid input/configuration
3 analysis could not complete
```

SARIF includes high/critical risk, limited/unsupported changed coverage,
stale graphs, unresolved public/API/database boundaries and failed explicit
targeted tests as applicable.

## Actions and privacy

Actions are structured objects with `id`, `kind`, `title`, `enabled`,
`requires_explicit_user_action`, `payload` and (when disabled)
`reason_disabled`. Supported kinds are `inspect_entity`,
`investigate_entity`, `explain_edge`, `run_recommended_test`, `open_file`,
`refresh_graph`, `view_coverage` and `acknowledge_warning`.

All mode builders accept local project paths and optional local graph paths.
They do not upload source, graph, diff, telemetry or project data. IDE, PR,
GitHub and GitLab integrations are future thin clients over this contract;
they are not part of this stage. VS Code/Kodik integration and PR/release
delivery come next.
