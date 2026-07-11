# Benchmarks

The public benchmark tree contains reproducible fixtures and runners only.
Generated reports are intentionally excluded from the main repository.

```text
benchmarks/
  fixtures/python/     # Python semantic resolver fixtures
  fixtures/polyglot/   # Go, Java, and cross-language fixtures
  latest_summary.json  # latest compact benchmark summary
```

Run the focused benchmark tests from the repository root:

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/test_benchmark_runner.py -q
```

Full benchmark matrices and generated reports belong in CI artifacts or a
separate benchmark-results branch, not in the product source tree.
