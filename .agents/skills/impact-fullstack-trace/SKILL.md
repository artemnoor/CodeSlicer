---
name: impact-fullstack-trace
description: Trace frontend-to-backend impact chains through components, hooks, API clients, HTTP wrappers, canonical endpoints, routes, services, and repositories. Use for fullstack projects and questions about what frontend code is affected by a backend change.
---

# Fullstack Impact Trace

Require endpoint identity, not function-name similarity.

## Workflow

1. Inventory languages, services, manifests, and frontend/backend roots.
2. Analyze with the configured TypeScript/JavaScript and Python providers.
3. Query the changed backend or frontend node with both directions and a
   bounded depth.
4. Follow the chain:
   `component -> hook -> client -> wrapper -> HTTP method/path -> backend route -> handler -> service -> repository`.
5. Use `explain-edge` on each cross-boundary edge.
6. Report service identity, HTTP method, canonical path, confidence, and
   unresolved dynamic path/wrapper diagnostics.

## Rules

- Match endpoints by service + HTTP method + canonical path.
- Do not connect `/orders` to `/orders-history` or GET to POST.
- Do not merge identical paths from different services.
- Tree-sitter structural edges are not Python semantic parity.
- Dynamic paths and ambiguous wrappers remain likely, ambiguous, or unresolved.

## Result

Return confirmed and likely chains separately, affected components/hooks/clients,
routes/services/tests, best evidence paths, and frontend/backend limitations.
