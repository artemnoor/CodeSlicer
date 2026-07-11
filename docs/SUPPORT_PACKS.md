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
