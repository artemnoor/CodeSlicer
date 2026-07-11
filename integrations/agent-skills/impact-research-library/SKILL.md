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

## Project-Specific Personalization

When the behavior is specific to one private SDK, wrapper or project
convention, do not edit the CodeSlicer repository. Create a candidate pack and
install it only under the target project:

1. Run `impact-engine project-packs init <project>`.
2. Create a candidate whose `evidence_requirements.forbid_name_only` is true.
3. Include import, receiver, type, decorator, provider, module or file
   evidence for call/binding rules.
4. Install it as `draft` first. After validation and a before/after graph
   comparison, use `--trust-level experimental` to activate it locally.
5. Re-run analysis and confirm every new edge has `scope: project_local`
   provenance.
6. If the rule becomes reusable, prepare a separate CodeSlicer PR with
   fixtures; never modify the shared registry automatically.

## When a Declarative Pack Is Not Enough

Project-local packs support declarative rules only. If the target behavior
needs a new executable resolver, parser capability, or a new kind of semantic
fact, the agent must stop before editing the CodeSlicer core and return a
proposal containing:

1. the unsupported pattern and concrete source locations;
2. the evidence chain the new resolver would require;
3. a minimal positive fixture, negative fixture, and mutation scenario;
4. expected edges and forbidden edges;
5. the proposed production module and test plan.

The agent may implement and validate this work on a dedicated branch or PR
only after the user authorizes a core change. It must never adapt the shared
GitHub repository silently for one project's private pattern.

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
