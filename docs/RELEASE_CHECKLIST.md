# Release Checklist — Impact Engine v0.4

This checklist summarizes the required steps to build and verify a stable local release.

## Step 1: Package Hardening & Install
- [x] Run `python -m pip install -e .` and verify the package is registered.
- [x] Execute `impact-engine --help` or verify installed console-script metadata when PATH does not expose the script in the test runner.
- [x] Confirm `requests` is declared because the research fetcher uses it.
- [x] Confirm Graphify is optional and not imported/executed by core analysis.

## Step 2: Automated Quality Gates
- [x] Run `python -m pytest -ra` and verify all tests pass (`189 passed in 4.28s`).
- [x] Assert `tests/test_acceptance.py` passes.
- [x] Assert `tests/test_acceptance_real.py` passes.
- [x] Assert `tests/test_packaging.py` passes.
- [x] Assert GraphDocument integrity tests pass.
- [x] Assert support-pack provenance tests pass.
- [x] Assert tree-sitter diagnostics/fallback tests pass.
- [x] Assert Graphify remains optional.
- [x] Assert acceptance docs truth tests pass.

## Step 3: Real CLI Smoke
- [x] `python -m impact_engine.cli analyze examples/golden_cases/python_di_basic --out tmp_acceptance_graph.json`
- [x] `python -m impact_engine.cli impact tmp_acceptance_graph.json --symbol repositories.OrderRepository.save --direction upstream --depth 3 --min-confidence 0.8`
- [x] `python -m impact_engine.cli explain-edge tmp_acceptance_graph.json --from services.OrderService.create_order --to repositories.OrderRepository.save`
- [x] `python -m impact_engine.cli detect-languages examples/golden_cases/python_di_basic`
- [x] `python -m impact_engine.cli inventory examples/golden_cases/python_di_basic`
- [x] `python -m impact_engine.cli research start examples/golden_cases/python_di_basic --library fastapi --ecosystem python`
- [x] Real subprocess tests use timeout/capture and isolated temp cwd.

## Step 4: Local SQLite and State Maintenance
- [x] Run `impact-engine db init` to initialize the database schema.
- [x] Run `impact-engine db runs` to check registered analysis runs.

## Step 5: MCP Tool Verification
- [x] Verify MCP tools return JSON-serializable dicts.
- [x] Verify MCP error paths return JSON-safe error payloads.
- [x] Verify `install_support_pack` exists as a user-facing alias over support-pack import.
- [x] Verify MCP non-research tools do not require internet.

## Step 6: Research Workflow Verification
- [x] Run `impact-engine research start <project_path> --library <name> --ecosystem <lang>` and verify workflow files are written to `.impact_engine/research_workflows`.
- [x] Validate candidate JSON support packs before installation.
- [x] Confirm normal analyze does not access the internet.
- [x] Monkeypatch fetchers in tests that prepare research input.

## Remaining Release Notes
- Python is the only production-supported language in this release.
- JS/TS/Go/Java extraction is useful for partial graph facts but remains experimental.
- Native tree-sitter parser usage is not documented as production multi-language support.
