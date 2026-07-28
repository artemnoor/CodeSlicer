# OpenAPI and AsyncAPI boundary overlays

CodeSlicer treats local API and event specifications as optional evidence, not
as a replacement for the canonical `.impact_engine` graph. An import is an
explicit action and accepts only an absolute local JSON/YAML path. No URL is
fetched, no server or broker is contacted, and no specification is generated.

| Adapter | Formats | Evidence | Review/risk | State |
| --- | --- | --- | --- | --- |
| OpenAPI | OpenAPI 3.x, Swagger 2.0 | operations, HTTP routes, schemas | never changes ranking/risk/tests | disabled until explicit import + enable |
| AsyncAPI | AsyncAPI 2.x, 3.x | channels, messages, producers, consumers | never changes ranking/risk/tests | disabled until explicit import + enable |
| SCIP | local semantic index | symbols and semantic relationships | separate overlay | independent adapter |
| LSP | explicitly configured local process | bounded runtime semantic facts | separate overlay | independent adapter |
| OpenTelemetry | OTLP JSON, Jaeger JSON | observed spans and runtime chains | never changes ranking/risk/tests | disabled until explicit import + enable |

Resolution is conservative: `operationId`-only matches are `likely`;
`confirmed` requires exact HTTP method + normalized route path, a stable
semantic ID, or exact file + complete range + kind evidence. Client-string and
name-only candidates are `likely` or `unresolved`, never `confirmed`. The
confirmed AsyncAPI event chain is `producer → channel → consumer`; operationId
or name matches alone do not confirm event mapping. A stale or unverified
specification is visible context and cannot increase confidence, ranking, risk,
or test recommendations.

```powershell
impact-engine adapters openapi import C:\project C:\specs\openapi.yaml
impact-engine adapters openapi enable C:\project
impact-engine adapters openapi status C:\project --json
impact-engine adapters asyncapi import C:\project C:\specs\events.yml
impact-engine adapters asyncapi enable C:\project
```

Only internal `$ref` values are resolved. Broken, cyclic, or external refs are
reported as diagnostics. Generated specifications, dynamic routes, GraphQL,
and gRPC are not yet modeled. AsyncAPI server/broker URLs are retained as
metadata only and are never used for a network connection.

OpenTelemetry is observational runtime evidence, distinct from static graph,
SCIP, LSP, and API/event contract overlays. Its confirmed relationships must
be present in the imported trace with complete trace/span evidence. Missing
trace coverage is `not observed`, not proof of no relationship. OTel imports
are local-only, redacted by attribute allowlist, bounded by file/span/depth
limits, and cannot mutate `.impact_engine` or influence Review.
