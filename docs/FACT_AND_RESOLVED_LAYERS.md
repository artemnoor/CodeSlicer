# Fact and Resolved Layers

Extractors produce raw facts: declarations, imports, callsites, assignments,
decorators, locations and route fragments. They do not claim semantic targets.
The pipeline records a `FactDocument` summary before semantic binding and then
produces the backward-compatible resolved `GraphDocument`.

The resolved graph contains canonical nodes, semantic edges, evidence,
provenance, confidence, resolution status and validation status. The current
public JSON remains compatible; the fact layer is exposed as metadata while the
internal model transition remains incremental.

Support packs are a rules context available to semantic binding, generic
precision resolution, framework resolution and validation. They are not a
single terminal stage.
