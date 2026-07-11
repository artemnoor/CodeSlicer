# Getting Started

This guide takes CodeSlicer from a clean checkout to a real project graph,
impact query, visual interface, and MCP connection.

## Requirements

- Python 3.10 or newer;
- Git;
- a writable local directory;
- Node.js only for browser verification or the analyzed project's own tools;
- Docker only for an optional container workflow.

Windows 10/11, Linux, and macOS are supported. CodeSlicer itself uses local
Python, SQLite, JSON, and HTTP APIs; it does not require Supabase or another
hosted service.

## Install

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

If PowerShell blocks activation, run the command in a terminal with an
appropriate execution policy or use the installed environment's Python
directly. Activation is only a shell convenience.

Verify the installation:

```bash
impact-engine doctor
impact-engine --json registry status
```

Expected registry mode:

```text
sqlite
```

## Analyze a Project

### 1. Review the scan scope

This is recommended for monorepos and workspaces containing dependencies or
generated output:

```bash
impact-engine scan-plan /path/to/project
```

The plan excludes dependency trees, build output, caches, `.git`,
`.impact_engine`, and nested Git repositories. Review the included files before
continuing. It does not modify the source project.

### 2. Build the graph

```bash
impact-engine analyze /path/to/project \
  --use-scan-plan \
  --out /path/to/project/.impact_engine/graph.json
```

For a small project, `--use-scan-plan` can be omitted. The command reports
progress in human-readable mode and keeps JSON output machine-readable when
`--json` is used. The graph, facts, registry, and research tasks are written
under `.impact_engine` in the analyzed project.

### 3. Inspect the result

```bash
impact-engine inventory /path/to/project
impact-engine detect-languages /path/to/project
impact-engine libraries detect /path/to/project
impact-engine impact /path/to/project/.impact_engine/graph.json \
  --symbol OrderService.create_order --direction both
impact-engine explain-edge /path/to/project/.impact_engine/graph.json \
  --from services.OrderService.create_order \
  --to repositories.OrderRepository.save
```

For agent integrations, put `--json` before the command:

```bash
impact-engine --json analyze /path/to/project \
  --out /path/to/project/.impact_engine/graph.json
```

## Start the Visual Interface

```bash
impact-engine-local-api \
  --host 127.0.0.1 \
  --port 8001 \
  --default-project /path/to/project
```

Open <http://127.0.0.1:8001/>.

The CLI and local API are separate processes. The API automatically hydrates
its state from `/path/to/project/.impact_engine/graph.json`, so a successful
CLI analysis is visible in the browser after the API starts. Verify the
handoff when debugging an empty graph:

```text
GET /api/health  -> status: ok
GET /api/state   -> has_analysis: true
GET /api/graph   -> nodes and edges from GraphDocument
```

For a graph at another location, use:

```json
POST /api/load-graph
{
  "project_path": "/path/to/project",
  "graph_path": "/path/to/graph.json"
}
```

The UI uses the real local API. It has no mock graph and no hosted database
connection.

## Start MCP

MCP uses JSON-RPC 2.0 over stdio:

```bash
impact-engine-mcp
```

Or:

```bash
python -m impact_engine.mcp.server
```

Use `initialize` followed by `tools/list` to discover the exact current
schemas. The tool groups cover project inventory, analysis, graph impact,
edge explanations, PR review, runtime observations, support packs, research
requests, and local registry operations.

## Unknown Libraries

When a third-party library is not known, the workflow is:

1. Detect and classify the dependency.
2. Create a research request with `impact-engine libraries research` or MCP.
3. Give the request to an external AI agent or human researcher.
4. Produce a candidate support pack with official-source provenance.
5. Validate schema, version range, positive fixtures, negative fixtures,
   mutations, determinism, and trust level.
6. Install only the validated pack.
7. Re-run analysis and compare the graph before and after.

The deterministic core does not call an LLM, directly write confirmed edges,
or silently approve a draft pack.

## Review a Diff Without Rebuilding the Project

This distinction is important for large repositories:

- `--diff-file` tells PR review which change to inspect;
- `--graph` supplies the already-built project graph;
- omitting `--graph` makes PR review analyze the whole project before it can
  inspect the diff.

Recommended workflow:

```powershell
impact-engine analyze C:\path\to\project `
  --use-scan-plan `
  --out C:\path\to\project\.impact_engine\graph.json

impact-engine pr-review C:\path\to\project `
  --diff-file C:\path\to\change.diff `
  --graph C:\path\to\project\.impact_engine\graph.json
```

Without `--graph`, a large project can take a long time because the diff does
not act as a parser scope. The command is working through a full analysis, not
necessarily frozen. If source files changed after the graph was created,
refresh it first or use the incremental analysis workflow.

Useful commands:

```bash
impact-engine libraries research /path/to/project \
  --library unknown_library \
  --ecosystem python \
  --build-input

impact-engine support-packs validate path/to/support_pack.json
impact-engine support-packs list
```

## Local Registry

The registry is local SQLite state:

```text
/path/to/project/.impact_engine/impact_registry.sqlite
/path/to/project/.impact_engine/registry_cache/
support_packs/<ecosystem>/<library>/support_pack.json
```

Check it with:

```bash
impact-engine registry status
```

## Run Tests

From the repository root:

```bash
python -m pytest -q
```

The suite includes parser and resolver tests, support-pack trust and
provenance checks, CLI subprocess tests, MCP stdio tests, incremental analysis,
real fixtures, and local API regression tests.

## Troubleshooting

### The browser shows an empty graph

1. Confirm the CLI wrote the graph to
   `<project>/.impact_engine/graph.json`.
2. Restart the API with the same `--default-project`.
3. Check `/api/state` and confirm `has_analysis: true`.
4. Check `/api/graph` and confirm that `nodes` and `edges` are non-empty.
5. Ensure the browser is connected to the same API port shown in the terminal.

### Analysis is unexpectedly slow

Run `scan-plan` first. Avoid analyzing `node_modules`, virtual environments,
build output, coverage directories, generated assets, and nested repositories.
The progress output identifies the stage that is taking time.

### A library is detected as unknown

This is expected when no trusted support pack covers its semantics. Create a
research request and validate a candidate pack; do not solve it by adding
name-only matching.

## Next Reading

- [Architecture](ARCHITECTURE.md)
- [MCP](MCP.md)
- [Support Packs](SUPPORT_PACKS.md)
- [Limitations](LIMITATIONS.md)
