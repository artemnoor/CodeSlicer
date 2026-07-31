# OpenAPI Boundary Adapter

This optional adapter imports an existing local OpenAPI 3.x or Swagger 2.0
document. It never downloads, generates, or contacts a service. Import is an
explicit user action and accepts only an absolute `.json`, `.yaml`, or `.yml`
path.

The adapter creates a separate `CodeSlicerBoundaryOverlay/v1`; it does not
write the canonical `.impact_engine` graph and does not affect Review ranking,
risk, or test recommendations. `operationId`-only matches are `likely`;
`confirmed` requires exact HTTP method + normalized route path, a stable
semantic ID, or exact file + complete range + kind evidence. Client-string or
name-only candidates are `likely` or `unresolved` and are never promoted to
confirmed.

Example:

```powershell
impact-engine adapters openapi import C:\project C:\specs\openapi.yaml
impact-engine adapters openapi enable C:\project
impact-engine adapters openapi status C:\project --json
```

Local `$ref` values are supported. External refs, broken refs, cycles, stale
specifications, generated-spec markers, dynamic routes, GraphQL, and gRPC are
reported as diagnostics or limitations. Server URLs are metadata only; no
network connection is made. SCIP and LSP remain separate semantic evidence
overlays.
