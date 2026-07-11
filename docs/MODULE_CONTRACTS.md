# Module Contracts

## impact_engine.models

Owns graph entities:

- Node
- Edge
- Evidence
- GraphDocument

No parsing/resolution logic here.

## impact_engine.analysis

Owns orchestration only:

- AnalysisOptions
- AnalysisResult
- AnalysisPipeline
- DiagnosticsCollector

Allowed:

- call inventory/language/extractor/normalizer/semantic/resolver modules in order
- preserve CLI/MCP-compatible result shape
- collect structured diagnostics

Forbidden:

- implement extractor logic
- implement resolver logic
- implement support pack rule semantics

## impact_engine.extractors.python_ast

Input:

```text
project path
```

Output:

```text
GraphDocument with EXTRACTED structural facts
```

Must preserve:

- receiver expression
- keyword args
- assignment target/value
- scope
- line numbers

## impact_engine.resolution.precision

Input:

```text
GraphDocument with extracted facts
```

Output:

```text
GraphDocument with INFERRED semantic edges
```

Main MVP:

```text
OrderService.create_order CALLS OrderRepository.save
```

## impact_engine.semantic

Input:

```text
GraphDocument with extracted and normalized structural facts
```

Output:

```text
same GraphDocument plus INFERRED cross-boundary semantic edges
```

Allowed edge kinds:

- ROUTE_HANDLES
- HTTP_CALLS
- MATCHES_ENDPOINT

Forbidden:

- overwrite ordinary CALLS edges
- replace Python precision resolver
- replace support pack rules

## impact_engine.impact

Input:

```text
graph + target symbol
```

Output:

```text
upstream/downstream affected nodes
```

## impact_engine.support_packs

Input:

```text
support pack JSON/YAML
```

Output:

```text
validated machine-readable library semantics
```

No network access in MVP.

## impact_engine.mcp.server

Thin wrappers around core functions.

Allowed:

- call analyzer
- call impact query
- call support pack validator
- create research request prompt

Forbidden:

- duplicate resolver logic
- hide errors
- become black box
