# Joern / CPG adapter

This is an optional `local-artifact` adapter. CodeSlicer never installs,
downloads, starts, or communicates with Joern. The user explicitly imports an
existing local JSON export or converter result.

Supported input is the bounded `CodeSlicerJoernInterchange/v1` subset with
safe node/edge IDs, method/function/call/control-flow/data-flow/source/sink
entities, file/range locations, bounded taint paths, and dangerous-call
findings. The stored artifact is a sanitized
`CodeSlicerJoernEvidenceOverlay/v1`; raw Joern properties, snippets, literals,
arguments, URLs, query payloads, headers, tokens, and arbitrary metadata are
discarded.

Complete source → steps → sink paths with complete identifiers and locations
may be `confirmed` when fresh. Incomplete or dynamic paths are `likely` or
`unresolved`. A dangerous-call pattern without a complete taint path is context
only, not a vulnerability claim. All output is bounded and supplemental; it
does not change canonical graph, Review ranking, risk, or test recommendations.
