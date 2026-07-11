# Quality Gates and Acceptance Criteria

## Gate A — Static Parsing
- Python AST extractor parses parameter names, decorators, constructor scopes, self-attribute assignments, call expressions, and module-level variables.
- JavaScript/TypeScript/Go/Java extractors are parser-backed if native parsers are available, and degrade to a deterministic local fallback when unavailable, ensuring normal analysis never depends on internet downloads.
- Non-Python extractors must return honest diagnostics, scale down fallback edge confidence to <= 0.60, and must not be documented as production semantic support. Python remains the only production-supported semantic baseline.

## Gate B — Semantic Inference
- Resolves DI call connections such as `services.OrderService.create_order CALLS repositories.OrderRepository.save` with source `INFERRED`, confidence >= 0.80, and trace evidence.
- Resolves routing connections with source `SUPPORT_PACK`, evidence, and `support_pack_rule_id`.
- Resolves test-to-route connections such as `tests.test_orders.test_create_order TESTS HTTP POST /orders`.
- Support-pack-created edges must never be marked `INFERRED`.

## Gate C — GraphDocument Integrity
- Nodes are deduped by id.
- Edges are deduped by from/to/kind/source/rule_id and conflict-resolved by source priority.
- Evidence is deduped to avoid repeated spam.
- Invalid node kinds, edge kinds, sources, and confidence values fail validation.
- Serialization/deserialization stays stable.

## Gate D — Package Runtime, CLI, and MCP
- `python -m pip install -e .` must succeed.
- `python -m pytest -ra` must pass.
- CLI outputs readable summaries by default, supports `--json`, and exits non-zero on validation errors.
- Fast CLI unit tests may use in-process `impact_engine.cli.main(argv)` dispatch.
- Real CLI E2E tests must exist separately and must run actual subprocess commands with `timeout=20`, `capture_output=True`, `text=True`, and `tmp_path` cwd/state isolation.
- The installed `impact-engine` console script must be checked through subprocess when available, or package entrypoint metadata must be checked honestly when the script is unavailable on PATH.
- Stdio JSON-RPC 2.0 MCP server exposes the documented tools and MCP functions return JSON-serializable dictionaries.
- Optional Graphify adapter parses external JSON structures safely without a mandatory Graphify dependency.

## Gate E — Research Workflow Safety
- Normal analyze must not access the internet.
- Internet use is restricted to explicit research commands.
- Fetching is bounded by HTTPS-only sources, max pages, timeout, max bytes, and no recursive crawling.
- Network tests must monkeypatch fetchers.
- AI output can only be validated as support-pack candidates; it cannot mutate the graph directly.

## Gate F — Test Runtime Stability and Truthful Docs
- Any `subprocess.run(...)` call in tests must set an explicit timeout.
- CLI tests must isolate cwd and temporary state where possible.
- A pytest-level watchdog must fail an individual hung test instead of allowing the full suite to block indefinitely.
- `docs/acceptance_status.json` may only set `tests_passed=true` when `docs/pytest_verification.json` records a completed zero-exit `python -m pytest -ra` run with the same command and summary.
- Acceptance docs must list Python as supported and JS/TS/Go/Java as experimental while the polyglot layer remains partial.
