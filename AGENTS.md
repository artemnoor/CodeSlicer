# Repository Guidance

## Scope

Impact Engine is a local-first deterministic analyzer. Do not add hosted
database dependencies to the core or UI. SQLite and the local JSON cache are
the registry of record.

## Required checks

    $env:PYTHONPATH = "src"
    python -m pytest -q
    impact-engine doctor
    impact-engine --json registry status

For UI changes, start impact-engine-local-api and verify /api/health, real
graph load, graph mode switching, exports, impact requests, and a clean
browser console.

For MCP changes, run a real stdio subprocess and validate JSON-RPC responses.

## Evidence rules

Extractors produce facts, resolvers produce edges, and AI research produces
candidate artifacts only. Never use name-only matching to create a confirmed
edge. Preserve provenance and report unresolved or ambiguous cases honestly.

## Analysis scope

Before analyzing a large or mixed workspace, run:

    impact-engine scan-plan C:\path\to\project

Review the deterministic included/excluded scope. It prunes virtualenvs,
`node_modules`, build outputs, caches, `.git`, `.impact_engine`, and nested Git
repositories. An agent may explain or request a scope change, but must not
silently exclude source files. Then run:

    impact-engine analyze C:\path\to\project --use-scan-plan

Use the scope plan when the workspace contains the CodeSlicer checkout itself,
generated dependencies, or multiple unrelated applications.
