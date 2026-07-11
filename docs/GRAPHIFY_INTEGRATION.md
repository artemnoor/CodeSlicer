# Graphify Integration

Graphify is an optional structural input adapter. It is not the Impact Engine
semantic resolver and it is not required for Python analysis.

The supported flow is:

```text
Graphify JSON (nodes + links)
  -> graphify adapter
  -> external GraphDocument facts
  -> normalizer / merge
  -> semantic binding and support-pack rules
  -> quality annotations
  -> impact query
```

Graphify edges are marked `source=EXTERNAL_TOOL` and receive a bounded,
low-confidence numeric value. The adapter preserves the external relation,
source file, source location, and dangling-reference warnings. It never turns
an external structural link into a confirmed inferred semantic edge.

## Operational Features

- `impact-engine analyze-incremental <project> --out graph.json` fingerprints
  project files and atomically replaces the graph after validation.
- `impact-engine watch <project> --iterations 2` runs bounded polling updates.
- `impact-engine graph-quality graph.json` reports orphans, dangling edges,
  duplicate IDs, and a stable graph fingerprint.
- `impact-engine visualize-compare graph.json graphify.json` opens separate
  Impact Engine and Graphify views; the datasets are never merged in the UI.
- MCP exposes `graph_quality` and `impact_path` in addition to the existing
  analysis/query tools.

Community and hub annotations are metadata only. They are useful for visual
grouping and navigation, but cannot create resolver edges or raise confidence.

## Safety Rules

- External URLs must be absolute HTTPS URLs.
- Research fetches do not follow redirects implicitly.
- Project paths must exist and be directories.
- Graph writes use a temporary file plus atomic replace.
- Graph quality warnings are surfaced instead of silently creating placeholder
  semantic nodes. When a resolver emits an alias for an existing qualified
  symbol, the alias is accepted; a truly unknown endpoint receives an explicit
  unresolved placeholder and its edge is quarantined from active impact.
- Every node receives a backward-compatible `properties.stable_id` based on
  project path, source file, qualified name, kind, and SHA-1.
- Unchanged incremental runs reuse the previous graph without invoking the
  analyzer. Changed runs remain correctness-first and reanalyze the project
  before atomic replacement.
