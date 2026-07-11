# CodeSlicer

**CodeSlicer** is a local-first static impact analyzer for codebases with
multiple languages, services, and frontend/backend boundaries. It builds an
evidence-backed graph of symbols and relationships, then answers questions
such as:

> If this repository method, route, service, or file changes, what should we
> inspect or test next?

The Python package and CLI use the internal package name `impact_engine`.

## Why CodeSlicer

Most dependency tools report that two files are related. CodeSlicer keeps the
reason for each relationship:

```text
source facts
  -> normalization
  -> semantic binding
  -> resolver evidence
  -> impact path
```

Every useful edge can carry its resolution status, confidence, evidence chain,
source facts, resolver attribution, and support-pack provenance. Ambiguous or
unsupported relationships stay visible as diagnostics instead of being
silently promoted to confirmed edges.

## Capabilities

- deterministic project inventory and scan planning;
- Python AST extraction with the strongest semantic coverage;
- structural and limited semantic extraction for JavaScript, TypeScript, Go,
  and Java through Tree-sitter when available;
- constructor, field, import, provider, nested-object, and receiver binding;
- frontend-to-backend endpoint matching using method, service, and canonical
  path rather than function-name similarity;
- framework/library support packs with versions, provenance, trust levels, and
  confidence caps;
- impact queries, edge explanations, PR review, and suggested tests;
- optional Python runtime observations that strengthen existing static edges;
- local SQLite registry and JSON cache, with no hosted database dependency;
- CLI, local MCP server, and a local 2D/3D graph viewer.

## Current Support Scope

| Area | Current status |
| --- | --- |
| Python | strongest semantic baseline |
| JavaScript / TypeScript | structural plus limited semantic and frontend endpoint resolution; fallback diagnostics remain possible |
| Go | structural plus limited semantic resolution; fallback extraction is explicit when Tree-sitter is unavailable |
| Java | structural plus limited semantic resolution; fallback extraction is explicit when Tree-sitter is unavailable |
| FastAPI, React, dependency-injector, SQLAlchemy, Celery | versioned support-pack rules where the pack is installed and trusted |
| Arbitrary frameworks and libraries | detected first; semantics require a validated support pack |

The system is not a compiler and does not claim perfect resolution of
reflection, runtime-selected DI, complex generics, generated proxies, or
untyped dynamic dispatch. See [Limitations](docs/LIMITATIONS.md).

## Quick Start

### 1. Install

Requirements: Python 3.10+, Git, and a writable local directory. Node.js is
optional for browser verification and Docker is optional for containerized
workflows.

Windows PowerShell:

```powershell
git clone https://github.com/artemnoor/CodeSlicer.git
cd CodeSlicer
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
```

Linux or macOS:

```bash
git clone https://github.com/artemnoor/CodeSlicer.git
cd CodeSlicer
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
```

Verify the installation:

```bash
impact-engine doctor
impact-engine --json registry status
```

The registry should report `mode: sqlite`.

### 2. Analyze a project

For a large or mixed workspace, inspect the scope before parsing it:

```bash
impact-engine scan-plan /path/to/project
impact-engine analyze /path/to/project --use-scan-plan \
  --out /path/to/project/.impact_engine/graph.json
```

On Windows PowerShell, use the equivalent Windows path and either a single
line or PowerShell's backtick for line continuation. The scan plan excludes
dependency trees, build output, caches, `.git`, `.impact_engine`, and nested
Git repositories. Review it before analysis when the workspace contains
multiple applications.

### 3. Query impact

```bash
impact-engine impact /path/to/project/.impact_engine/graph.json \
  --symbol repositories.OrderRepository.save --direction both

impact-engine explain-edge /path/to/project/.impact_engine/graph.json \
  --from services.OrderService.create_order \
  --to repositories.OrderRepository.save
```

Use `--json` before the subcommand when another tool or agent needs structured
output.

## Local Visual Interface

The UI is a local viewer for the real GraphDocument. It does not contain a
mock graph and does not connect to Supabase or another hosted database.

```bash
impact-engine-local-api --host 127.0.0.1 --port 8001 \
  --default-project /path/to/project
```

Open <http://127.0.0.1:8001/>. The API automatically loads the existing
`<project>/.impact_engine/graph.json` created by the CLI. Verify:

```text
GET /api/state  -> has_analysis: true
GET /api/graph  -> the graph payload
```

If the graph is stored elsewhere, load it with `POST /api/load-graph` and a
`project_path` plus `graph_path`. See [Getting Started](docs/GETTING_STARTED.md)
for the complete API list and troubleshooting steps.

## MCP

CodeSlicer exposes a local JSON-RPC MCP server over stdio:

```bash
impact-engine-mcp
```

The server provides tools for health checks, inventory, language detection,
analysis, impact queries, edge explanations, PR review, runtime tracing,
support-pack validation, and library research workflows. Use JSON-RPC
`tools/list` as the authoritative schema. See [MCP](docs/MCP.md).

## Unknown Libraries

Unknown-library handling is evidence-gated:

```text
detect dependency
  -> create research request
  -> external AI or human researches official sources
  -> produce candidate support pack
  -> validate schema, provenance, fixtures, negatives, and mutations
  -> promote trust level
  -> re-run deterministic analysis
```

The core does not call an LLM or silently invent confirmed edges. A researcher
may create a candidate artifact, but the local validation and trust gates
decide whether it can participate in ordinary analysis. See
[Support Packs](docs/SUPPORT_PACKS.md).

## Graph Output

Analysis writes a `GraphDocument` JSON artifact with:

- `nodes`: files, modules, classes, functions, methods, routes, tests, and
  external libraries;
- `edges`: imports, calls, bindings, route handling, HTTP calls, endpoint
  matches, and other typed relationships;
- `metadata`: languages, diagnostics, coverage, unknown regions, fingerprints,
  resolver information, and support-pack provenance.

Nodes have stable canonical identities and source locations. Edges include
confidence and evidence when available. A graph is a diagnostic model, not a
guarantee that every dynamic runtime path has been resolved.

## Repository Map

```text
src/impact_engine/       deterministic engine, CLI, MCP, local API
support_packs/            versioned framework/library rules
frontend/                 local graph viewer
tests/                    unit, fixture, CLI, MCP, and regression tests
examples/                 small reproducible example projects
docs/                     detailed usage, architecture, limits, and MCP
integrations/agent-skills agent workflows for analysis and impact review
```

## Documentation

- [Getting Started](docs/GETTING_STARTED.md) - installation, analysis, UI,
  registry, tests, and troubleshooting;
- [Architecture](docs/ARCHITECTURE.md) - pipeline, graph model, and trust
  boundaries;
- [MCP](docs/MCP.md) - local server, tools, and safety boundary;
- [Support Packs](docs/SUPPORT_PACKS.md) - library semantics and validation;
- [Limitations](docs/LIMITATIONS.md) - honest boundaries of static analysis.

## Development

```bash
python -m pytest -q
impact-engine doctor
impact-engine --json registry status
```

The project is local-first. Generated graphs, caches, SQLite state, and
benchmark output belong in `.impact_engine` or other ignored paths, not in the
source-controlled product documentation.
