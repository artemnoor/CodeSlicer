# Graph Schema

## Node kinds

- PROJECT
- FILE
- MODULE
- CLASS
- FUNCTION
- METHOD
- PARAMETER
- ATTRIBUTE
- CALL_EXPR
- ASSIGNMENT
- ROUTE
- TEST
- EXTERNAL_LIBRARY
- SUPPORT_PACK

## Edge kinds

- CONTAINS
- IMPORTS
- DECLARES
- ASSIGNS
- READS
- WRITES
- CREATES
- INSTANCE_OF
- PARAM_BINDS_TO
- FIELD_BINDS_TO
- RESOLVES_TO
- CALLS
- MAY_CALL
- DEPENDS_ON
- ROUTE_HANDLES
- TESTS
- AFFECTS
- PROVIDED_BY_SUPPORT_PACK

## Edge source

- EXTRACTED — direct syntax extraction
- INFERRED — deterministic inference by resolver
- RUNTIME_CONFIRMED — runtime/test tracing confirmation
- EXTERNAL_TOOL — imported from Graphify/JARVIS/etc.
- SUPPORT_PACK — generated from support pack rules
- AI_PROPOSED — proposed by AI, not verified

## Evidence

Every inferred/support-pack edge must have evidence:

```json
{
  "file": "services.py",
  "line": 7,
  "description": "self.repository.save(order) receiver resolved to OrderRepository"
}
```

## Confidence

Suggested scale:

- 1.00 explicit type annotation / runtime confirmed
- 0.95 direct constructor assignment
- 0.90 constructor arg + param-to-field propagation
- 0.80 receiver resolution from propagated field
- 0.60 naming/single-candidate heuristic
- <0.60 weak edge / should not be used as strong impact

## Independent edge dimensions

`confidence` is numeric evidence strength; it is not a validation status.
Edges may also carry:

- `resolution_status`: `resolved`, `proposal`, `ambiguous`, or `unresolved`;
- `evidence_class`: `static_proven`, `static_inferred`, `support_pack_rule`,
  `runtime_observation`, `ai_proposed`, or `manual`;
- `validation_status`: `not_validated`, `runtime_observed`, or
  `runtime_only_observation`;
- `observations`: all static/runtime/support-pack observations retained during
  deduplication.

Runtime observation proves only that a call was seen in a named test and
environment. A missing observation is `not_observed`, not a rejection. Runtime
calls that cannot be mapped to static endpoints remain quarantined under
`metadata.runtime_only_observations`.
