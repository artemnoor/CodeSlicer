# AsyncAPI Boundary Adapter

This optional adapter imports an existing local AsyncAPI 2.x or 3.x document.
It is disabled by default, accepts only an absolute local `.json`, `.yaml`, or
`.yml` path, and never connects to broker/server URLs or performs downloads.

It produces a separate `CodeSlicerBoundaryOverlay/v1` with bounded
producer/channel/message/consumer evidence. The confirmed event chain is
`producer → channel → consumer`; operationId or name matches alone are only
`likely`, and unmapped channels remain `unresolved`. The overlay cannot mutate
`.impact_engine` or change Review ranking, risk, or tests.

```powershell
impact-engine adapters asyncapi import C:\project C:\specs\events.yaml
impact-engine adapters asyncapi enable C:\project
impact-engine adapters asyncapi status C:\project --json
```

Local internal `$ref` values are supported. External/broken/cyclic refs,
generated specs, dynamic channels, GraphQL, and gRPC are diagnostics or known
limitations. SCIP and LSP are separate evidence layers.
