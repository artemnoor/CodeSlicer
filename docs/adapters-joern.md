# Joern / CPG local adapter

Joern is a heavy, explicit opt-in investigation adapter. CodeSlicer does not
install or launch Joern, pull Docker images, contact a network endpoint, send
source code, or collect telemetry. Import an already-created local JSON export:

```powershell
impact-engine adapters joern import C:\path\to\project C:\absolute\path\joern-interchange.json --json
impact-engine adapters joern enable C:\path\to\project --json
impact-engine adapters joern status C:\path\to\project --json
impact-engine adapters joern disable C:\path\to\project --json
impact-engine adapters joern convert C:\absolute\path\graph.json --project C:\path\to\project --output C:\absolute\path\interchange.json --json
```

`joern convert` is an explicit local bridge for native Joern GraphSON
(`@type`/`@value`, `vertices`, `edges`) and bounded CPGQL path-result JSON. It
normalizes `METHOD`, `CALL`, `IDENTIFIER`, `METHOD_PARAMETER_IN`, `FILE`,
`LITERAL`, and `CONTROL_STRUCTURE` vertices. `AST`, `CFG`, `REACHING_DEF`,
`CDG`, `CALL`, and `REF` edges are normalized to the existing interchange
`CONTAINS`, `CONTROL_FLOW`, `DATA_FLOW`, or `CALL` kinds with a safe
`source_kind` marker.

The bridge keeps only opaque deterministic IDs, safe relative files, bounded
line/range data, short redacted snippets, confidence and generated JSON
pointers. Unknown properties, full source, secrets and raw GraphSON IDs are
discarded. Conversion writes a new local interchange file; it does not modify
`.impact_engine` or invoke Joern.

The supported interchange subset is `CodeSlicerJoernInterchange/v1`: bounded
methods/functions, calls, control-flow/data-flow edges, source/sink nodes,
taint paths, dangerous-call findings, safe relative files, complete ranges,
bounded IDs and optional JSON pointers. Unknown schemas produce an
`unsupported` diagnostic and no invented evidence. The imported normalized
overlay is stored under `.codeslicer/artifacts/joern/`; raw source artifacts
remain at their user-selected local path and are not copied.

Before a demo or CI run, verify that the installed CLI is the checkout being
tested. This check does not install anything and does not run Joern:

```powershell
python scripts/check_cli_installation.py
```

The command clears Python import overrides before probing
`impact-engine --json adapters joern convert --help`, so a stale executable
cannot appear healthy merely because `PYTHONPATH=src` is inherited. The command
exits non-zero when the executable is old, incompatible, or missing. The CI
workflow additionally creates a clean venv, runs `pip install -e ".[dev]"`,
and checks the command from that venv's `PATH`.

## Evidence rules

`CPG_STATIC` covers structural CPG facts. `CPG_DATAFLOW` covers data-flow and
taint context. A taint path is `confirmed` only when the export contains a
non-empty source → steps → sink path, every ID resolves to an imported node,
the path contains at least two complete safe locations, source and sink nodes
both have complete file/range locations, and freshness is `fresh` with
`verified: true`. Missing locations, incomplete ranges, stale, dynamic, or
unresolved paths remain `likely` or `unresolved` and receive an explicit
diagnostic. A dangerous call without a complete taint path
is a supplemental finding/context item, never a claim that a vulnerability was
found. Stale or incomplete exports remain visible as warnings and cannot raise
Review risk, ranking, or targeted tests.

AST, CFG, CDG, CALL, REF and REACHING_DEF edges alone are never a confirmed
security impact. A security path is created only from an explicit
`taint_paths`, `paths`, or `dataflow_paths` CPGQL result. Simple graph
reachability is not a taint claim.

Every stored node, edge, path and finding uses a strict recursive allowlist:
stable IDs, normalized kinds, safe relative file/range, bounded path/finding
IDs, severity/category, confidence/resolution, and bounded provenance. Raw
properties, snippets, literals, SQL, URLs, arguments, descriptions, headers,
tokens and environment values are not retained or rendered. Unsafe external
node, edge, path, finding, source, sink, or step IDs are deterministically
replaced with opaque local SHA-256 identifiers; raw IDs are never retained,
while internal connectivity is preserved.

The scope is C/C++/Java CPG and security/data-flow investigation. Dynamic
dispatch, reflection, macros, native bindings, incomplete exports and Joern
query coverage remain limitations. “No finding” or no observed path does not
mean that the code is safe.
