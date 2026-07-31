# CodeGraph compatibility adapter

This optional local-only adapter imports an existing absolute-path CodeGraph
compatible JSON artifact. It supports nodes identified by `id`/`key`/`file`/
`symbol` and explicit `import`, `call`, and `contains` edges. Unsupported
schemas, edge kinds, dangling endpoints, and missing evidence are reported as
diagnostics rather than converted into guessed relationships.

The normalized overlay is stored under `.codeslicer/artifacts/codegraph/`;
the raw source is not copied. The source path and SHA-256 are retained only so
freshness can be checked. `network_used=false` is always reported.

External graph evidence is `DOC_INFERRED`, marked with source and provenance,
and is overlay-only. It can supplement explanations in Inspect/Investigate,
but does not change the canonical `.impact_engine` graph, Review risk/ranking,
or targeted-test recommendations. A relationship is `confirmed` only when
the imported artifact explicitly supplies sufficient evidence; otherwise it is
`likely` or `unresolved`.

Example:

```powershell
impact-engine adapters codegraph import C:\project C:\exports\codegraph.json
impact-engine adapters codegraph enable C:\project
impact-engine adapters codegraph status C:\project --json
```
