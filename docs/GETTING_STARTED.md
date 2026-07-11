# Getting Started

Impact Engine is a local static impact analyzer. The source project, graph,
SQLite registry, support packs, MCP server, CLI, and visual interface can all
run on the same machine. No hosted database is required.

## Install

Requirements:

- Python 3.10 or newer;
- Git;
- Node.js is optional and only needed for browser verification;
- Docker Desktop is optional.

From the repository root:

    py -3 -m venv .venv
    .venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip
    pip install -e .

Verify the installation:

    $env:PYTHONPATH = "src"
    impact-engine doctor
    impact-engine --json registry status

The registry status must report mode: sqlite.

## Analyze a project

For a large workspace, inspect the deterministic scope first:

    impact-engine scan-plan C:\path\to\project

This prunes dependency trees, generated output, caches, and nested Git
repositories before source extraction. Review the result, then analyze with:

    impact-engine analyze C:\path\to\project --use-scan-plan --out .impact_engine\graph.json

    impact-engine analyze C:\path\to\project --out .impact_engine\graph.json

The command writes a GraphDocument JSON artifact. It does not modify the
analyzed source tree. Runtime state and caches are stored below .impact_engine.
During a human-readable CLI run, progress is printed as weighted stages with
the current stage, processed units, total units, and overall percentage. JSON
CLI output remains machine-readable; progress diagnostics are sent to stderr.

Useful follow-up commands:

    impact-engine inventory C:\path\to\project
    impact-engine detect-languages C:\path\to\project
    impact-engine libraries detect C:\path\to\project
    impact-engine impact .impact_engine\graph.json --symbol OrderService.create_order --direction both
    impact-engine explain-edge .impact_engine\graph.json --from services.OrderService.create_order --to repositories.OrderRepository.save

## Start the visual interface

    $env:PYTHONPATH = "src"
    impact-engine-local-api --host 127.0.0.1 --port 8001 --default-project C:\path\to\project

Open http://127.0.0.1:8001/.

The UI uses the real local API:

- GET /api/health
- GET /api/state
- GET /api/graph
- GET /api/inventory
- POST /api/analyze
- POST /api/impact
- POST /api/query
- GET /api/progress

The UI has no mock graph or external database connection.

## Start MCP

MCP uses JSON-RPC 2.0 over stdio:

    impact-engine-mcp

The authoritative tool list is returned by tools/list. The server exposes
analysis, impact, explain, runtime, support-pack, research-queue, and local
registry tools.

## Local registry

SQLite is the only registry backend:

- database: .impact_engine/impact_registry.sqlite;
- portable cache: .impact_engine/registry_cache;
- support packs: support_packs/<ecosystem>/<library>/support_pack.json.

To create a local research request:

    impact-engine registry create-research-request python unknown-library
    impact-engine registry status

Research input is written locally and can be handed to an external AI agent.
The deterministic engine validates the resulting support pack before it can
be installed.

## Run tests

    $env:PYTHONPATH = "src"
    python -m pytest -q

The suite covers CLI subprocesses, MCP stdio, parser diagnostics,
support-pack trust/provenance, incremental analysis, real fixtures, and the
local registry API.
