# Performance and incremental benchmark harness

This harness is local-only and never downloads a corpus.  It reports wall
clock timings, cache reuse and correctness metadata; node counts are context
only and are never used as a performance proxy.

Run the mandatory synthetic fixture:

```powershell
python benchmarks/performance/runner.py --synthetic --output benchmarks/performance/baseline/synthetic.json
```

Run a local corpus only when it exists:

```powershell
python benchmarks/performance/runner.py --corpus tests/corpus/JunMate --scope .
```

Missing corpora produce `status: corpus_unavailable` and include a reproducible
local command instead of fabricated measurements.  CI should run the
synthetic case; real corpora are opt-in.

The report includes p50/p95 for review and impact queries, cache hit/miss
reasons, invalidated/reused facts, deterministic semantic equivalence, peak
memory when tracemalloc is available, and explicit SLO booleans.
It also includes monotonic stage profiling and non-content work counters for
initial, warm, incremental, and review runs.

Checked-in local results currently include:

- `baseline/synthetic.json`: synthetic SLO and differential baseline.
- `baseline/JunMate.json`: real corpus, `.` scope; differential passed and
  warm/incremental SLOs are met in the current run.
- `baseline/Cruxa.frontend.json`: real Cruxa `frontend` scope; differential
  passed and all measured SLOs are met in the current run.
- `baseline/CodeSlicer.analysis.json`: real repository `src/impact_engine/analysis`
  scope; differential passed and all measured SLOs are met in the current run.
- `baseline/mamAI.json` and `baseline/Pixel Compressor.json`: explicit
  `corpus_unavailable` reports; no fabricated timings.

These are evidence reports, not a claim that synthetic SLOs hold for large
repositories.
