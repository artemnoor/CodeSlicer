# OpenTelemetry Runtime Evidence Adapter

The optional OTel adapter imports an already exported local trace file. It is
disabled by default and accepts only an absolute local path through an
explicit CLI/API action. CodeSlicer never connects to OTLP, Jaeger, Tempo,
Zipkin, Docker, a broker, or an external network, and it never starts an
application or collector.

Supported formats are OTLP JSON export (`resourceSpans`) and Jaeger JSON export
(`data[].spans`). The imported artifact is stored at
`.codeslicer/artifacts/otel/trace.json`; state is stored at
`.codeslicer/adapters/otel.json`. Raw attributes are not retained. Only a
small allowlist of routing, service, database, messaging, status, and source
metadata is kept; secrets, authorization, cookies, tokens, credentials and
request/response bodies are redacted.

```powershell
impact-engine adapters otel import C:\project C:\traces\export.json
impact-engine adapters otel enable C:\project
impact-engine adapters otel status C:\project --json
impact-engine adapters otel disable C:\project
```

Runtime edges are observational. A span relationship that is present with
complete trace/span evidence is `confirmed`; missing spans are `not observed`,
never proof that a relationship does not exist. An `HTTP_CLIENT_SERVER` edge
is confirmed only by an explicit parent-child relationship, the same explicit
allowlisted correlation ID, or an explicit span link. Matching only
`trace_id + HTTP method + route` is never evidence and creates no edge.
Mapping to the canonical graph is confirmed only by exact HTTP method +
normalized route from server-side evidence, exact normalized service +
operation metadata, stable semantic ID, or exact file + complete range + kind;
client spans may only map strongly to an explicitly frontend/client node.
Service-only, route-only, name-only, and ambiguous matches are `likely` or
`unresolved`; stale traces are context-only. OTel never mutates
`.impact_engine` and never changes Review risk, ranking, or test
recommendations.

OTLP span links preserve only their trace/span identity and sanitized
allowlisted attributes. Jaeger `FOLLOWS_FROM` and other well-formed reference
types are treated as link-like evidence; malformed links are reported as
diagnostics and cannot confirm a relationship.

The overlay is distinct from static CodeSlicer evidence, SCIP semantic index,
LSP runtime queries, and OpenAPI/AsyncAPI boundary contracts. Trace coverage
depends on the workload and sampling used to create the export. An absent
trace does not imply an absent code path. Large files, span counts, attribute
values, and parent depth are bounded and reported as diagnostics.
