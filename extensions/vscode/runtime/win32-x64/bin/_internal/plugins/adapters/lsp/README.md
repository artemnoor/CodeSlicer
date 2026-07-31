# Local LSP Semantic Adapter

The LSP adapter is optional, disabled by default, and local-only from
CodeSlicer's transport perspective. CodeSlicer starts an already installed
local Language Server only after an explicit `probe` or `query` action. It
never downloads, installs, discovers, or starts a server during analyze,
Review, Inspect, or ordinary status calls.

Configuration is stored as metadata in `.codeslicer/adapters/lsp.json`.
Bounded facts are stored in `.codeslicer/artifacts/lsp/overlay.json`; source
text and the canonical `.impact_engine` graph are never copied or modified.
The configured executable and every workspace root must be an absolute local
path. A project and returned LSP file URI must remain inside an allowed root.

## CLI

```powershell
$env:PYTHONPATH = "src"

impact-engine adapters lsp status C:\work\project --json
impact-engine adapters lsp configure C:\work\project `
  --executable C:\tools\typescript-language-server.cmd `
  --workspace-root C:\work\project
impact-engine adapters lsp probe C:\work\project --json
impact-engine adapters lsp query C:\work\project `
  --method definition --file src\main.ts --line 10 --character 8 `
  --entity-id symbol:main --json
impact-engine adapters lsp disable C:\work\project
```

The optional `--arg` flag is a list of literal local process arguments, useful
for a server wrapper or deterministic test server. URL/network endpoint
arguments (`http://`, `https://`, `ws://`, `wss://`, `ftp://`, and URI-like
tokens) are rejected. The CLI never uses shell interpretation for the command.

Privacy boundary: `network_used=false` means that CodeSlicer itself opened no
network transport. The configured executable is an arbitrary user-selected
local process and is **not sandboxed**; its own network behavior is not
observed by CodeSlicer (`subprocess_network=not_observed`). Use an OS/container
firewall or a trusted server executable if a hard no-network guarantee is
required. The API exposes this distinction in the `privacy` object.

Supported bounded methods:

| LSP method | Support | Notes |
|---|---|---|
| `initialize` / `shutdown` / `exit` | available | short-lived subprocess lifecycle |
| `textDocument/documentSymbol` | partial | requires the server capability |
| `textDocument/definition` | partial | exact URI/range facts only |
| `textDocument/references` | partial | bounded to 200 locations |
| `textDocument/implementation` | partial | only when advertised |
| `workspace/symbol` | partial | only an explicit query, bounded |

Language server matrix:

| Server family | Status | Boundary |
|---|---|---|
| TypeScript language server / tsserver wrapper | available when locally installed | server command and capabilities vary by installation |
| Pyright | available when locally installed | no automatic Python environment or server setup |
| Roslyn / C# language server | partial | only advertised LSP capabilities are used; no MSBuild/build orchestration |

## Evidence rules

The overlay uses `CodeSlicerLspEvidenceOverlay/v1` and
`evidence_class=LSP_RUNTIME`. Each node records the local server, capability,
timestamp, file URI and complete LSP range. Mapping is confirmed only by a
stable semantic ID or exact source file + complete range + kind. Same-name
matches are `unresolved`; multiple exact candidates are `ambiguous`.
Timeouts, malformed JSON-RPC, unavailable servers, unsupported capabilities,
outside-root URIs and stale source files remain visible diagnostics.

LSP is live/ephemeral context; SCIP is an imported semantic index with its own
artifact freshness. Neither overlay changes the canonical CodeSlicer graph,
Review risk, ranking, or targeted tests. Inspect and bounded Investigate may
display the last explicitly queried LSP overlay. `network_used=false` is
CodeSlicer's transport observation, not a sandbox guarantee for the child
process; see the privacy boundary above.

Mock JSON-RPC coverage is always part of the normal test suite. Real-server
compatibility is a separate opt-in check and never installs anything:

```powershell
$env:PYTHONPATH = "src"
pytest -m lsp_interop -q
```

The test probes `typescript-language-server` and `pyright-langserver` when
they are already on `PATH`; Roslyn can be supplied through the absolute
`CODESLICER_ROSLYN_LSP` environment variable. Missing servers are skipped;
an installed but non-working server is reported as a test failure.
