# CodeSlicer / Impact Engine v0.4

Impact Engine is a dependency-injection-aware static impact analysis system designed for multi-language codebases. It features a deterministic core engine, Python AST precision resolution, multi-language tree-sitter extraction, support packs, and an AI-backed research workflow.

## Core Features

- **Deterministic Core**: The analysis pipeline is entirely deterministic and orchestrated by `AnalysisPipeline`: `inventory/languages` -> `extractors` -> `normalize/merge` -> `semantic binding` -> `precision resolver/support packs` -> `impact graph`. The core analysis does not require internet connection.
- **Python AST Precision Baseline**: Deep class-field constructor tracking, global variable bindings, and nested resolver chains (e.g. tracking `container.service.create_order` to repository methods).
- **Multi-language Tree-Sitter Layer**: High-extensibility extraction of Javascript, Typescript, and Go code patterns.
- **Semantic Binding Layer**: A vendored universal binding layer converts extracted graph facts plus lightweight source facts into object-flow and endpoint-flow edges such as `ROUTE_HANDLES`, `HTTP_CALLS`, and `MATCHES_ENDPOINT`.
- **Fullstack Endpoint Bridge**: A deterministic frontend/backend bridge connects static JS/TS HTTP wrappers, path helpers, and backend route prefix chains when enough evidence exists.
- **Nested Object Graph Resolver**: Multi-hop object receivers such as UOW/repository fields and literal mapping aliases are resolved into evidence-backed `CALLS` edges.
- **PR Review Mode**: Diff-based analysis maps changed files/symbols to impact, risk, and suggested tests.
- **Runtime Trace Booster**: Optional Python test tracing can confirm existing static edges and boost confidence for observed call paths.
- **Library Support Packs**: Declared JSON-based frameworks/libraries patterns (FastAPI, React, Dependency Injector) that map routes, containers, or components into the semantic impact graph.
- **AI Researcher Boundary**: When unknown libraries are detected, the system generates research prompts and executes bounded URL fetching for selected research sources to produce schema-validated candidate support packs. No real LLM API is called; deterministic analysis relies on the static parser, precision resolver, and verified support packs.
- **Local SQLite State**: Initializes local schema and exposes APIs/CLI for recording and listing analysis runs and support pack metadata.
- **Optional Graphify Integration**: Enables loading external Graphify-like JSON outputs, converting them to normalizer-compliant structures, and running query pipelines.

## Current Product Status

Impact Engine v0.4 is a working local MVP/product baseline, not a fully autonomous self-learning agent yet.

What works today:
- A project can be analyzed through CLI or MCP.
- Analysis uses a typed orchestration layer (`AnalysisOptions`, `AnalysisResult`) with structured diagnostics.
- The system detects project languages, declared dependencies, external imports, and local modules.
- Python code is analyzed with the precision AST extractor and resolver (our only production-supported semantic baseline).
- JavaScript, TypeScript, Go, and Java receive parser-backed structural extraction through the native tree-sitter parser if available, or degrade to local regex fallback extraction (no production semantic resolver claims for non-Python languages yet).
- Extracted graphs are normalized into the unified `GraphDocument` format.
- The semantic binding layer can connect nested backend routers to frontend HTTP wrapper calls when enough static evidence exists.
- The endpoint bridge can create `HTTP_CALLS` and `MATCHES_ENDPOINT` edges from frontend API clients to backend route handlers.
- The nested object graph resolver handles UOW-style chains and literal mapping aliases where static evidence is available.
- Impact output is bucketed into confirmed, likely, weak, suspicious, rejected, and not-resolved groups.
- PR review mode can produce structured impact/risk/test recommendations from a diff.
- Runtime trace mode can run Python tests and boost graph edges that are actually observed.
- Support packs can add deterministic framework/library semantics.
- Impact queries can answer what is upstream/downstream of a symbol, file, route, or inferred edge.
- Edge explanations return confidence, source, evidence chain, and support-pack rule metadata when available.
- Unknown libraries can be detected and converted into bounded research workflow inputs.
- Candidate `support_pack.json` files can be validated and installed locally.

What is intentionally not automatic yet:
- The system does not call a real LLM API.
- The system does not fully crawl the internet.
- The system does not automatically generate, approve, and install support packs without an agent or human review step.
- The system is not expected to understand every language, framework, dynamic runtime pattern, or private dependency with perfect accuracy.
- Runtime trace boosting currently targets Python test runs and matching existing static graph edges; it is not a general runtime tracer for every language.

The intended current workflow is:
1. Analyze a real project.
2. Inspect graph, impact query, and explain-edge output.
3. Detect unknown libraries.
4. Generate a library research request/input pack.
5. Use an AI/human researcher to produce a machine-readable support pack.
6. Validate and install that support pack.
7. Re-run deterministic analysis with the new library semantics available.

## External AI Library Researcher

An optional external researcher is maintained separately as the sibling project
`ai_library_researcher_pro`; set `IMPACT_RESEARCHER_PRO_ROOT` when it is elsewhere.
It is intentionally outside the deterministic Impact Engine core. Its job is to research
unknown libraries, produce a machine-readable `support_pack.json`, validate it, and install
it into `support_packs/<ecosystem>/<library>/support_pack.json`.

Run it independently:

```powershell
cd ..\ai_library_researcher_pro
pip install -e .
python -m ai_library_researcher_pro.cli --help
```

Impact Engine consumes only the validated support pack artifact; it does not depend on AI,
network access, or the researcher at analysis time.

## Documentation

- [Getting started](docs/GETTING_STARTED.md)
- [Architecture](docs/ARCHITECTURE.md)
- [MCP](docs/MCP.md)
- [Support packs](docs/SUPPORT_PACKS.md)
- [Limitations](docs/LIMITATIONS.md)

The local visual client is split into `frontend/index.html`, `frontend/styles.css`,
`frontend/app.js`, `frontend/api-client.js`, `frontend/graph-2d.js`, and
`frontend/graph-3d.js`. It talks only to the local API and does not contain a
mock graph or hosted database integration.

## Semantic Binding Layer

The universal semantic binding layer is vendored under `src/semantic_binding` and integrated through `impact_engine.semantic`.
It is intentionally a separate module, because it solves a different class of problems than the language parser:

- language extractors produce structural facts;
- the semantic binding layer resolves object graph flow, route prefixes, endpoint wrappers, returned object destructuring, and backend/frontend endpoint matching;
- support packs still own framework-specific deterministic rules.

The current integration only imports cross-boundary semantic edges back into Impact Engine:
`ROUTE_HANDLES`, `HTTP_CALLS`, and `MATCHES_ENDPOINT`. It does not override ordinary `CALLS` edges from extractors or precision/support-pack resolvers.

## CLI Usage

Install the package locally:
```bash
pip install -e .
```

Run project analysis:
```bash
impact-engine analyze examples/golden_cases/python_di_basic --out graph.json
```

Query downstream/upstream impact:
```bash
impact-engine impact graph.json --symbol repositories.OrderRepository.save --direction upstream
```

Run PR impact review from a diff:
```bash
impact-engine --json pr-review C:\path\to\your\project --diff-file change.diff
```

Boost a graph with a Python runtime trace:
```bash
impact-engine runtime-trace C:\path\to\your\project --graph graph.json --out graph.runtime.json -- python -m pytest -q
```

Explain a semantic edge:
```bash
impact-engine explain-edge graph.json --from services.OrderService.create_order --to repositories.OrderRepository.save
```

Detect languages:
```bash
impact-engine detect-languages examples/golden_cases/python_di_basic
```

Project inventory scan:
```bash
impact-engine inventory examples/golden_cases/python_di_basic
```

List support packs:
```bash
impact-engine support-packs list
```

Validate a support pack file:
```bash
impact-engine support-packs validate support_packs/python/fastapi/support_pack.json
```

Analyze a real local project:
```bash
impact-engine analyze C:\path\to\your\project --out graph.json
impact-engine impact graph.json --symbol some.package.Symbol --direction both --min-confidence 0.5
impact-engine inventory C:\path\to\your\project
impact-engine research start C:\path\to\your\project --library unknown_library_name --ecosystem python
```

Production control commands:
```bash
impact-engine doctor
impact-engine libraries detect C:\path\to\your\project
impact-engine libraries research C:\path\to\your\project --library unknown_library_name --ecosystem python --build-input
impact-engine libraries research C:\path\to\your\project --library unknown_library_name --ecosystem python --allow-network
impact-engine libraries research C:\path\to\your\project --library unknown_library_name --ecosystem python --pro --install-draft
impact-engine libraries research C:\path\to\your\project --library unknown_library_name --ecosystem python --pro --install-draft --confirm-install
impact-engine libraries research C:\path\to\your\project --library unknown_library_name --ecosystem python --pro --install-draft --confirm-install --overwrite
impact-engine qa run C:\path\to\qa_projects --out-dir .impact_engine\qa_runs
```

The older `research ...` and `support-packs ...` commands remain supported for compatibility.
Researcher-pro drafts can also be adapted directly:

```bash
impact-engine support-packs adapt-pro-draft .impact_engine\research_workflows\<id>\support_pack_draft.json --out adapted_support_pack.json
impact-engine support-packs install .impact_engine\research_workflows\<id>\support_pack_draft.json
impact-engine support-packs install .impact_engine\research_workflows\<id>\support_pack_draft.json --overwrite
```

`--install-draft` stages adapted researcher drafts under `support_packs/.staging/...` by default. Use
`--confirm-install` to write into the main registry, and `--overwrite` only when replacing an existing pack is intentional.

## MCP Server Design

The server runs over Standard I/O (stdio) and supports JSON-RPC 2.0 communication. It exposes 29 callable tools:
- `health_check`
- `server_info`
- `analyze_project`
- `impact_query`
- `explain_edge`
- `pr_review`
- `runtime_trace`
- `detect_unknown_libraries`
- `detect_languages`
- `project_inventory`
- `list_support_packs`
- `validate_support_pack`
- `import_support_pack`
- `install_support_pack`
- `create_library_research_request`
- `create_library_research_workflow`
- `prepare_library_research_input`
- `validate_library_research_candidate`
- `install_library_support_pack`

Start the MCP server:
```bash
impact-engine-mcp
```
or:
```bash
python -m impact_engine.mcp.server
```

## Known Limitations

- **Static Traversal**: Dynamic routes (constructed via runtime variable concatenations) and reflection API calls are not resolved statically.
- **External Imports Boundaries**: Requires a registered library support pack rules schema to infer dependencies past package borders.
- **Offline Mode Fetching**: The fetcher respects rate-limits and limits recursion to prevent recursive fetching.
