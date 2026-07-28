# Python external golden

Indexer: `@sourcegraph/scip-python@0.6.6`.

Materialized artifact SHA-256: `c0a1931ae26caa18c57e2183c2f0366c4ce50856b6a9cab51ff55a48de810caa`.

The official `0.6.6` package has a native-Windows path separator bug in its
environment helper. Generate this golden from local WSL Ubuntu instead:

```powershell
wsl -d Ubuntu -- bash -lc "cd '/mnt/c/<repo>/tests/fixtures/scip/golden/python/project' && npm install --global @sourcegraph/scip-python@0.6.6 && scip-python index . --project-name codeslicer-scip-python-golden"
Get-FileHash .\tests\fixtures\scip\golden\python\project\index.scip -Algorithm SHA256
```

Set `status` to `materialized` and record the SHA-256 in `manifest.json`. Expected evidence is `add` defined in
`app/util.py`, referenced by `total` in `app/main.py`, plus definitions for
`total`; no interface implementations in this fixture. Ranges are legacy
packed Python source ranges (the parser also supports typed ranges). The
command follows the official scip-python usage (`scip-python index .
--project-name ...`).
The generated metadata contains a `file://` root under WSL; Windows
CodeSlicer therefore reports it as foreign or unverified rather than claiming
freshness.
