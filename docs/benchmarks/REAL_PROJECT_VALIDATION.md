# Real-project CLI validation

This page is the human-readable companion to the versioned
[`real-project-cli-validation-2026-08-03.json`](real-project-cli-validation-2026-08-03.json)
snapshot. It records one reproducible Windows x64 run of the installed
CodeSlicer source checkout, not a cross-machine performance promise.

## What was executed

Each repository was obtained at the pinned SHA in
[`benchmarks/real_projects/manifest.json`](../../benchmarks/real_projects/manifest.json).
The runner creates a disposable working copy and performs:

1. CLI `analyze --use-scan-plan` from a cold project state.
2. A second CLI `analyze` to verify a persistent cache hit.
3. CLI `review` of the repository's actual `HEAD~1..HEAD` diff.
4. CLI `review --refresh auto` after a minimal source-anchored comment change.

The final step is a negative control: a comment-only change must not create
invented impact edges. Project dependencies were not installed and the
projects' own test suites were not run; this is a CodeSlicer CLI validation,
not a claim about third-party build health.

## Snapshot — 2026-08-03

| Public project | Pinned revision | Scope | Files / LOC | Graph nodes / edges | Cold / warm analysis | Real-diff review | Freshness control |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| [FastAPI](https://github.com/fastapi/fastapi) | `4ef68e8` | `.` | 3,099 / 98,269 | 35,819 / 40,374 | 95.14 s / 17.04 s | Low, high confidence; 0 impacts | Low, high confidence; 0 impacts; 72.31 s |
| [Gin](https://github.com/gin-gonic/gin) | `34dac20` | `.` | 118 / 20,415 | 10,498 / 11,752 | 16.10 s / 4.24 s | Low, high confidence; 0 impacts | Low, high confidence; 0 impacts; 15.24 s |
| [Express](https://github.com/expressjs/express) | `a371447` | `.` | 201 / 17,629 | 9,156 / 1,514 | 11.74 s / 2.93 s | Low, high confidence; 0 impacts | Low, high confidence; 0 impacts; 10.48 s |
| [Cruxa](https://github.com/contr4s/Cruxa) | `13ff4a0` | `backend` | 564 / 33,752 | 5,739 / 8,202 | 25.98 s / 4.19 s | Unknown / limited coverage; 10 impact entities from a 7-file diff | Unknown / limited coverage; no invented impact for comment-only edit; 7.13 s |

All mechanical gates passed: pinned revision, non-empty cold graph, warm cache
hit, review schema/no-error contract, and expected language detection. The raw
JSON contains the exact schema, full reason strings and timings.

The Cruxa result is deliberately not upgraded to a success claim for C#
semantic precision: it reports `UNKNOWN` when cross-file closure cannot be
proven. This is the intended evidence-gated behavior. Likewise, the zero-impact
results in the other three controls mean that a comment-only change did not
manufacture a risk finding.

## Real browser E2E — Local Hub

On the same date, the browser path was run on a fresh clone of
[Spring PetClinic](https://github.com/spring-projects/spring-petclinic) at
`88e37c15cf6fc8490b01bc3e8e2c800cec1ac272`. CodeSlicer built its canonical
graph, then Chromium opened Local Hub's map and selected `HTTP GET /owners`.
The UI rendered the graph and preserved the confirmed outgoing
`processFindForm · ROUTE_HANDLES` edge. The scenario passed. It is a focused
end-to-end assertion for the served browser UI and its real Java project graph;
it does not run PetClinic itself.

## Reproduce

The command below clones the pinned public repositories. To avoid network use,
first prepare a directory with `fastapi`, `gin`, `express`, and `cruxa`
subdirectories at the manifest SHAs, then provide `--source-root`.

```powershell
$env:PYTHONPATH = "src"
python scripts/run_real_project_benchmarks.py `
  --output docs/benchmarks/local-real-project-validation.json

# Offline/reused clones:
python scripts/run_real_project_benchmarks.py `
  --source-root C:\corpora\codeslicer-real-projects `
  --output docs/benchmarks/local-real-project-validation.json
```

The output includes only public repository URLs, pinned revisions, aggregate
counts and timings. It omits local paths, source contents, tokens and project
dependency installation state beyond the explicit `false` flag.
