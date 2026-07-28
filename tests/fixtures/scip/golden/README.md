# External SCIP interoperability corpus

This directory is a reproducible, opt-in corpus for independent SCIP
indexers. The checked-in source projects and manifests are deterministic. The
generated `index.scip` files are intentionally not fabricated: they must be
created locally by the pinned external tool command in each language README.

| Language | Independent indexer | Pinned manifest version | Artifact in this checkout | Verification |
|---|---|---:|---|---|
| TypeScript | `@sourcegraph/scip-typescript` | `0.3.16` | materialized, SHA recorded | generated and parser-verified; lint passed |
| Python | `@sourcegraph/scip-python` | `0.6.6` | materialized, SHA recorded | generated in WSL; parser/lint passed; Windows root is foreign |
| C# | `scip-dotnet` | `0.2.14` | materialized, SHA recorded | generated; parser passed; lint exposes upstream namespace diagnostic |

The version pins are part of the reproducibility recipe, not a claim that the
tools are installed in every checkout. After regenerating a command explicitly,
set `status` to `materialized`, record the resulting SHA-256 in that language's `manifest.json`, and keep the
binary at the path named by the manifest. Do not replace it with a hand-written
protobuf fixture: those remain under `tests/fixtures/scip/*.base64` and are
covered by the parser tests, not by this interoperability corpus.

Run the opt-in verification from the repository root:

```powershell
$env:PYTHONPATH = "src"
python -m pytest -m scip_interop -q
impact-engine adapters verify-scip --json
```

Both commands are local-only. They do not install an indexer, download the
SCIP CLI, upload an index, or contact Sourcegraph. If `scip` is on `PATH`, the
explicit verifier runs `scip lint` for each materialized artifact.
