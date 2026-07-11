# Support Packs

Support packs provide versioned, library-specific extraction and resolver rules
without putting framework logic into the language core.

Each pack records its library, language, supported versions, rule IDs,
provenance, evidence requirements, confidence caps, trust level, fixtures, and
negative cases. The registry accepts a pack only after schema validation and
the relevant deterministic benchmark checks.

Trust lifecycle:

```text
draft -> staged -> experimental -> verified_on_fixture
      -> verified_on_real_project -> trusted
```

AI research can create candidate artifacts and evidence reports, but cannot
write confirmed graph edges directly. The engine validates and promotes packs
through the local SQLite registry.

Installed packs live under:

```text
support_packs/<ecosystem>/<library>/support_pack.json
```

## Project-local packs

Project-local packs personalize analysis for private wrappers, internal SDKs
and project-specific conventions without changing the shared CodeSlicer
registry. They live beside the analyzed source tree:

```text
<project>/.impact_engine/local_packs/<language>/<library>/support_pack.json
```

Create the directory, validate and install a candidate:

```bash
impact-engine project-packs init /path/to/project
impact-engine project-packs install /path/to/project candidate_pack.json \
  --trust-level experimental
impact-engine project-packs list /path/to/project
```

The loader gives project-local packs precedence over a shared pack with the
same `(language, library)` key. Their provenance is attached to emitted edges
with `scope: project_local` and `project_scope` metadata.

Local packs are subject to the same schema and trust policy, plus:

- `scope` is always `project_local`;
- `project_scope` is recorded when installed;
- `evidence_requirements.forbid_name_only` must be `true`;
- rules that match calls or constructor bindings require import, receiver,
  type, decorator, provider, module or file evidence;
- `draft` and `staged` packs are inactive;
- local packs can reach at most `verified_on_real_project`;
- `trusted` is reserved for the shared registry after a reusable review.

An AI agent may write a candidate pack into the project-local directory, but
it never writes graph edges directly. It must validate the pack, re-run
analysis and inspect the provenance and false-positive risk. A pattern that
proves reusable belongs in a normal CodeSlicer PR with fixtures and tests.
