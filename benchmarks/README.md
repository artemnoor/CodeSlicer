# Benchmarks

The public benchmark tree contains reproducible fixtures and runners. Full
machine-specific reports remain CI artifacts, while curated, sanitized,
versioned real-project snapshots are published in
[`docs/benchmarks`](../docs/benchmarks/REAL_PROJECT_VALIDATION.md).

```text
benchmarks/
  fixtures/python/     # Python semantic resolver fixtures
  fixtures/polyglot/   # Go, Java, and cross-language fixtures
```

Run the focused benchmark tests from the repository root:

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/test_benchmark_runner.py -q
```

Full benchmark matrices and generated reports belong in CI artifacts or a
separate benchmark-results branch. The one exception is a small, reviewable
real-project summary with pinned public revisions and aggregate metrics; it
exists so the README can make evidence-backed claims without committing any
third-party source tree.
