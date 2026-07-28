# Joern / CPG real-corpus validation

`impact_engine.adapters.joern_benchmark` is a local-only quality harness for
already-created `CodeSlicerJoernInterchange/v1` exports. It performs:

1. explicit import;
2. explicit enable;
3. bounded `Investigate` context;
4. aggregate precision/recall, calibration, explanation, privacy, freshness,
   latency and Review-invariance metrics.

It never starts Joern, runs a subprocess, downloads anything, or accesses the
network. The default report is written to the project-local
`.codeslicer/history/joern-validation/` directory and contains no overlay,
source snippets, raw external IDs or arbitrary properties.

## Run one local case

```powershell
$env:PYTHONPATH = "src"
impact-engine adapters joern benchmark `
  C:\absolute\project `
  C:\absolute\joern-interchange.json `
  --case-file C:\absolute\golden-cases.json `
  --case-id cpp-orders `
  --json
```

The command accepts only absolute local paths. Use explicit bounds such as
`--max-nodes 80 --max-edges 160 --max-paths 40` for comparable runs.

To inventory already available local exports:

```powershell
impact-engine adapters joern discover C:\absolute\search-root --max-files 5000 --timeout 10 --json
```

Discovery uses pruned directory walking. `.git`, `.impact_engine`,
`.codeslicer`, `node_modules`, build/dist/out/target/bin/obj/coverage/venv and
`graphify-out` are excluded by default; `tests/fixtures` and `corpus` are also
excluded unless `--include-synthetic` is explicitly supplied. `--max-files`
and `--timeout` are hard bounds, so a large monorepo returns a diagnostic and
asks for narrower roots instead of scanning indefinitely. The result separates
`real_candidates` from `synthetic_candidates`. Fixtures under `tests/fixtures`
are regression baselines only and must never be reported as real Joern
validation.

## Golden case format

See `golden_cases.example.json`. A case contains a case ID, language, absolute
project and artifact paths, source artifact fingerprint, expected path
resolutions, prohibited false-positive path IDs, dangerous-call context and a
location requirement. Expected IDs must be safe IDs or already-remapped opaque
IDs; secrets and raw external properties are rejected.

Precision and recall are reported only when expected IDs are supplied. Without
a golden expectation the harness reports observed counts and leaves precision,
recall and false-confirmed count as `null` rather than inventing quality.

## Validity rules

Only a non-empty source → steps → sink path with all IDs resolved, complete
source/sink and path locations, and `freshness.verified=true` can be confirmed.
Missing/incomplete locations, stale/foreign artifacts, dynamic paths and
dangerous calls without a taint path remain likely/unresolved diagnostics.
Absence of a path is not evidence that a vulnerability or relationship is
absent.

The Review signature (`risk`, top impacts and test recommendations) must remain
identical before and after the supplemental overlay. A missing canonical graph
is reported as `review_invariance.status=unavailable`, not treated as a pass.

## Current local-corpus result

The checked-in fixtures remain synthetic format/policy baselines only. A
separate local validation workspace ran the pinned real profiles with Joern
4.0.588 and Java 21:

| Case | Result |
| --- | --- |
| `vul4c-cve-2017-7607` | 2 explicit Joern flows; 2 imported confirmed paths, 1 semantic match |
| `vul4j-10-cve-2013-2186` | 1 explicit Joern flow; 1 imported confirmed path, 1 semantic match |

Only sanitized aggregate reports generated directly by the runner were
retained; no CPG or raw query output is checked in. The
Java path is `ObjectInputStream` parameter → `defaultReadObject` inside the
real vulnerable `DiskFileItem.readObject`; it does not independently prove
the CVE or framework exploitability. The C path reaches `handle_gnu_hash` and
is likewise an explicit data-flow validation, not a standalone CVE discovery.

Known limitations: this stage validates the CodeSlicer interchange and its
evidence policy, not Joern query quality or source-language extraction. It does
not claim vulnerability absence and does not replace independent Joern
analysis.

## Real vulnerability cases

Use `real_corpus_manifest.json` with
`scripts/run_joern_real_corpus_validation.py` for the pinned Vul4C C and Vul4J
Java profiles. The runner is strictly opt-in: provide an already local corpus,
an already installed Joern executable, and an installed CodeSlicer CLI. It
executes the local frontend and `reachableByFlows(...).toJson`, converts the
bounded result, imports/enables the overlay, and exits non-zero when the
expected confirmed path is absent. It never clones a repository, downloads a
tool, invokes Docker, or sends data to a network.

The repository does not contain those upstream checkouts or real Joern output.
X42 and the checked-in sanitized flow fixtures remain synthetic format and
policy baselines, not real vulnerability results.

The real manifest separates upstream metadata from runnable source material:
the C case requires a verified local extraction of the pinned elfutils archive,
and the Java case requires a separate Commons FileUpload checkout at the
pinned vulnerable commit. The runner verifies these prepared roots locally and
does not clone, fetch, download or extract them.

The real manifest does not accept positional `flow-0` or numeric vertex IDs as
proof. It uses case-specific semantic selectors for source and sink node kind,
symbol name, file suffix and minimum path length. Opaque IDs are retained only
for bounded graph connectivity.
