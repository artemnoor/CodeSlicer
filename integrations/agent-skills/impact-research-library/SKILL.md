---
name: impact-research-library
description: Handle an unknown library with Impact Engine's evidence-gated research workflow. Use when inventory or analysis reports an unknown third-party library, missing framework semantics, or a request to study official documentation and create a support pack.
---

# Research Unknown Library

AI research produces a candidate pack, never direct graph edges.

## Workflow

1. Confirm the dependency is not stdlib, local, workspace, dev-only, or an
   already available support pack.
2. Prepare the research task with:
   `impact-engine --json libraries research <project> --ecosystem <eco> --library <name> --build-input`
   Add `--allow-network` only when the user explicitly authorizes fetching.
3. Research only official documentation, official repository, official
   examples/tests, and package metadata. Record URL, version, pattern,
   evidence hash/snippet, and research date.
4. Produce a candidate support pack with rules, provenance, version range,
   confidence caps, fixtures, forbidden cases, and mutations.
5. Validate it with `support-packs validate` before installation.
6. Install only after schema, positive, negative, mutation, determinism, and
   trust-level gates pass.
7. Re-analyze the project and compare graph/unknown-region metrics before and
   after. Keep the pack experimental when evidence is insufficient.

## Prohibitions

- No name-only matching.
- No direct edits to GraphDocument.
- No automatic promotion to trusted.
- No unofficial source as the sole evidence.
- No claim that absence of a match proves absence of a relationship.

## Result

Return sources, candidate pack path, validation report, trust transition,
before/after graph metrics, newly resolved edges, remaining unknowns, and
limitations.
