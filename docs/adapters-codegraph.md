# CodeGraph / Graphify compatibility

CodeSlicer remains the owner of the canonical local impact graph. Graphify
and CodeGraph imports are optional, explicit, local artifact overlays. No
network request, subprocess, raw source upload, or raw artifact copy is made.

## Supported schemas

| Adapter | Input | Status |
|---|---|---|
| Graphify | JSON `nodes` plus `edges` or `links` | ready/incomplete/unsupported |
| CodeGraph | JSON `nodes` plus explicit `import`, `call`, or `contains` edges | ready/incomplete/unsupported |

Each imported entity carries adapter source, local source path, JSON pointer
when supplied, confidence/resolution, and `overlay_only=true`. The sanitized
overlay is stored in `.codeslicer`; source SHA-256 and project Git context are
used for stale detection. Changed source, foreign project, or missing source
is reported as stale/unverified.

External graph imports persist only allowlisted normalized evidence: stable
identity, kind/name, safe relative file and range, edge endpoints/kind, and
bounded provenance pointers. Arbitrary node/edge properties, metadata,
labels, descriptions, URLs, payloads, headers, tokens, and nested unknown
fields are discarded recursively. The same sanitation rules apply identically
to Graphify and CodeGraph; raw external properties and provenance payloads are
never stored in `.codeslicer`.

```powershell
impact-engine adapters list C:\project --json
impact-engine adapters graphify import C:\project C:\project\graphify-out\graph.json
impact-engine adapters codegraph import C:\project C:\exports\codegraph.json
impact-engine adapters codegraph enable C:\project
```

External evidence can be shown in Review explanations, Inspect, and bounded
Investigate with its source label. It never mutates `.impact_engine` and never
changes Review risk, ranking, or test recommendations. Unknown schema,
unsupported edge kinds, name-only relationships, and dangling endpoints are
`unresolved`/diagnostics, not confirmed facts.
