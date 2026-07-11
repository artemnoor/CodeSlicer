# Architecture

## Runtime boundary

    CLI / MCP / Local HTTP API
              |
              v
    AnalysisPipeline
      inventory and dependency classification
      pre-hygiene
      language extractors
      raw facts
      normalization
      semantic binding
      precision resolvers
      support-pack rules
      quality guard
      derived annotations
              |
              v
    GraphDocument + diagnostics + local registry state

The core is deterministic. AI research is an evidence-producing workflow
outside the graph truth boundary. An AI agent can propose a support pack, but
it cannot directly write confirmed graph edges.

## Extractors and resolution

- Python uses the AST extractor and the strongest semantic baseline.
- JavaScript, TypeScript, Go, and Java use native Tree-sitter when available.
- When native Tree-sitter is unavailable, the adapter reports an explicit
  degraded status and uses a bounded fallback.
- Extractors emit facts. Resolvers create semantic edges only when an evidence
  chain exists.

Support packs are versioned deterministic rules. Each pack carries source
provenance, rule IDs, trust level, confidence caps, fixtures, and validation
metadata.

## Graph model

Nodes carry stable canonical identity, language, workspace, module, qualified
name, kind, and source location. Edges carry from, to, edge kind, resolution
status, confidence, evidence chain, source facts, dependency keys, resolver ID,
and support-pack attribution.

Impact paths use the weakest edge status on the path. Suspicious and
unresolved edges never enter the confirmed result.

## Incremental analysis

Incremental analysis stores per-file raw facts and fingerprints. A changed
file produces a FactDiff, which drives the reverse dependency index, affected
closure, selective resolver passes, edge replacement, quality guard, and
deterministic fingerprint comparison with a clean rebuild.

The invariant is:

    incremental core semantic fingerprint == clean rebuild fingerprint

## Local persistence

LocalRegistryStore owns the SQLite schema and lifecycle operations. RegistryClient
is a local facade over SQLite plus JSON cache files. There is no Supabase
adapter, remote registry mode, or network database dependency.

The source tree and graph artifacts stay local to the user project. The
registry stores language profiles, library metadata, support packs, research
requests, and documentation hashes.
