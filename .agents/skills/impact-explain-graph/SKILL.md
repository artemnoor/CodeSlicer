---
name: impact-explain-graph
description: Explain a graph node, edge, or impact chain using Impact Engine evidence, provenance, resolver attribution, confidence, and diagnostics. Use when a user asks why two symbols are connected or why a node appears in impact results.
---

# Explain Graph Evidence

Use the graph's stored evidence rather than reconstructing a reason from names.

## Workflow

1. Locate the exact source and target node IDs.
2. Run:
   `impact-engine --json explain-edge <graph.json> --from <from> --to <to>`
3. Read source, kind, confidence, resolution status, validation status,
   evidence chain, source fact IDs, dependency keys, resolver ID, and support
   pack rule attribution.
4. Explain each step in order and identify the weakest link.
5. If the edge is missing, report that it was not found and inspect unknown
   regions; do not invent a candidate edge.

## Result

Return `found`, exact edge identity, confidence/status, provenance, evidence
files and lines, reasoning steps, support-pack rule/version/trust, warnings,
and any unresolved or ambiguous boundary.
