# Acceptance Report

This document reports the real QA verification status for Impact Engine v0.4 after the endpoint bridge, nested object graph, PR review, and runtime trace booster integration pass.

## Final Verification Summary

- **Total Tests Passed**: 291 tests via `python -m pytest -ra`
- **Real CLI subprocess E2E**: enabled and passing. `python -m impact_engine.cli ...` commands are executed through `subprocess.run(..., timeout=20, capture_output=True, text=True)` with isolated `tmp_path` cwd/state.
- **Console script**: `impact-engine` is checked through a real subprocess when present on PATH; otherwise the installed package metadata entrypoint is checked honestly.
- **MVP Edge Resolved**: Yes
  - `services.OrderService.create_order CALLS repositories.OrderRepository.save`
  - Source: `INFERRED`
  - Confidence: `0.85`
  - Evidence Count: `4`
  - Verifies full Python DI + FastAPI routing prefix composition + React TS component-hook-fetch chain E2E in `tests/fixtures/final_acceptance_project`.
- **Production Supported Languages**: Python (the only production-supported semantic baseline)
- **Experimental / partial languages**: JavaScript, TypeScript, Go, Java (parser-backed structural extraction if native parsers are available, otherwise degraded local regex fallback)
- **Tree-sitter status**: `native` or `partial_native` if parser pack is available, degrading to `partial_local_fallback` when unavailable; no claim of a production semantic resolver for all languages.
- **MCP Server Stdio tools count**: 19 tools, including `pr_review`, `runtime_trace`, and the user-facing `install_support_pack` alias.
- **Graphify integration status**: Optional adapter only; core does not import or execute Graphify.
- **Normalizer edge check**: Normalization does not invent inferred semantic edges.
- **Support-pack provenance**: Edges emitted by support-pack hooks are inferred semantic edges with `source=INFERRED` and explicit provenance metadata: `support_pack_id`, `support_pack_rule_id`, and `resolver_hook_name`.
- **Research workflow boundary**: Normal `analyze` does not access the internet. Research fetches are explicit and bounded; tests monkeypatch fetchers.
- **Frontend/backend endpoint bridge**: Available. It can connect frontend HTTP wrappers and path helpers to canonical backend routes when static source evidence is sufficient.
- **Nested object graph resolver**: Available. It resolves multi-hop receiver chains such as UOW/repository fields and literal mapping aliases.
- **Edge quality discipline**: Available. Impact output separates confirmed/likely/weak/suspicious/rejected buckets and suspicious edges are excluded from the confirmed traversal by default.
- **PR review mode**: Available through CLI and MCP. It maps diffs to changed graph nodes, impact, risk, and suggested tests.
- **Runtime trace booster**: Available as an optional post-analysis step for Python test runs. It can boost confidence for static edges confirmed by runtime call traces.
- **Support pack trust enforcement**: Available. `draft` and `staged` packs are skipped during normal analysis; active packs are capped by trust level: `experimental <= 0.65`, `verified_on_fixture <= 0.80`, `verified_on_real_project <= 0.90`, `trusted <= 0.95`.
- **Unified support-pack provenance**: Available. Support-pack edges include a single `properties.support_pack` object with pack ID, rule ID/version, trust level, resolver hook, matched pattern, and evidence. `explain-edge` returns this as `rule_attribution`.
- **Language semantic capability diagnostics**: Available. Analyze output reports honest per-language capability flags. Python is the production semantic baseline; JS/TS are extended structural/endpoint providers; Go/Java are structural providers with limited call facts.
- **JS/TS semantic hardening**: Available for bounded static evidence. The endpoint bridge handles barrel exports, `@/` aliases, nested path helpers, common HTTP wrappers/clients, and React component/hook/test relation edges.
- **Real Project QA Matrix**: Available. `impact-engine qa run tests/fixtures/qa_matrix` analyzes four externally generated projects and checks required edges, forbidden false positives, unknown-library detection, and tracked known gaps.

## Accepted Capabilities Matrix

### 1. MVP DI resolving
Resolves class dependency injection in Python AST:
`services.OrderService.create_order CALLS repositories.OrderRepository.save` with source `INFERRED`, confidence `0.85`, and evidence count `4`.

### 2. Route Chain
Resolves HTTP route chains in FastAPI-style fixtures. Route edges created by framework support packs use `source=INFERRED` plus support-pack provenance metadata.

### 3. Test-to-Route Edges
Connects API calls inside test suites such as `client.post("/orders")` to target route nodes with kind `TESTS`.

### 4. CLI Runtime
Both layers are covered:

- fast in-process parser/dispatch tests for deterministic unit coverage;
- real subprocess E2E smoke tests for installed/module runtime behavior.

Every subprocess CLI test has an explicit timeout and captured output.

### 5. MCP Tool Runtime
MCP tools return JSON-serializable dictionaries, report errors as JSON-safe payloads, and delegate analysis/resolution to core services.

### 6. Graphify Optional Adapter
External Graphify-like JSON can be normalized through an adapter without importing Graphify, running a Graphify subprocess, or making network calls.

### 7. Research Workflow Boundary
Research workflow is bounded and explicit. Normal `analyze` does not access the internet. Research commands prepare and validate support-pack candidates, and tests monkeypatch network fetches.

### 8. React / Polyglot Support
React and JS/TS/Go/Java extraction remain experimental/partial. The docs do not claim production polyglot analysis.

### 9. Fullstack Endpoint Bridge
The bridge resolves deterministic frontend-to-backend endpoint chains when the project exposes enough static evidence:

- frontend constants/path helpers/wrappers;
- HTTP method and canonical route;
- backend route prefix composition;
- matched frontend HTTP call to backend route handler.

It is a bounded static resolver, not a full TypeScript compiler.

### 10. Nested Object Graph
The nested resolver handles deterministic multi-hop object access patterns, including:

- `self.uow.orders.mark_paid(...)`;
- `self.uow.commit(...)`;
- `self.payment_service.charge_for_order(...)`;
- `self.nested_alias["orders"].save(...)`.

Edges include confidence and evidence; unresolved or weak edges should remain outside confirmed output.

### 11. PR Review Mode
`pr-review` accepts a project and diff input, maps changed files/symbols to graph nodes, runs impact query, and returns a structured review result with risk and suggested tests.

### 12. Runtime Trace Booster
`runtime-trace` runs a Python command under a local trace collector, maps observed calls back to graph edges, and writes a boosted graph. It is optional and does not replace static analysis.

## Current Operating Model

1. A project path is passed through CLI or MCP.
2. The inventory scanner detects languages, manifests, declared dependencies, external imports, local modules, files, classes, methods, and LOC.
3. Python AST and local deterministic fallback extractors build raw graph facts.
4. The normalizer converts extracted/adapted inputs into `GraphDocument` without inventing inferred semantic edges.
5. The precision resolver adds deterministic inferred edges with confidence and evidence.
6. Support-pack hooks add support-pack-provenance edges with confidence and evidence.
7. Fullstack endpoint and nested object graph resolvers add deterministic semantic edges where evidence is sufficient.
8. Post-hygiene and edge-quality classification annotate confirmed, likely, weak, suspicious, and rejected edges.
9. Impact query, explain-edge, and PR review operate over the resulting graph.
10. Runtime trace booster can optionally confirm existing static edges after a Python test run.
11. Unknown libraries can be turned into bounded research requests/input packs.
12. Validated `support_pack.json` files can be installed and used by later deterministic analysis runs.

Explicit boundary:

- Core analysis does not require internet access.
- The system does not call a real LLM API.
- The system does not autonomously generate and approve support packs.
- Unknown-library research is a workflow boundary: another agent or human researcher produces the candidate support pack, then Impact Engine validates and installs it.
- JavaScript/TypeScript/Go/Java extraction is partial/experimental, not production-level semantic analysis.
- Runtime trace boosting currently targets Python test runs and existing graph edges.

## Latest Verification

```text
python -m pytest -ra
291 passed in 25.27s
```

The old order-dependent CLI hang has been addressed without dropping real CLI coverage: unit CLI tests are in-process, while `tests/test_cli_subprocess_e2e.py` proves the actual module/console runtime through bounded subprocess calls.
