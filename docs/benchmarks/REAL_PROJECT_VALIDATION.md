# Real-project change-impact validation

This report answers a useful question: when a real function changes, what did CodeSlicer identify, and did a real project test observe the regression? The machine-readable source of truth is [`real-project-cli-validation-2026-08-03.json`](real-project-cli-validation-2026-08-03.json).

## Evidence model

Each proof case uses a pinned public repository and a disposable copy. It builds the baseline graph, applies one reversible behavior-changing edit, reviews the exact diff against the baseline graph, then runs one explicit target test three times: baseline must pass, the deliberate regression must fail, and restoring the exact source must pass.

The test is an independent oracle. This proves that the stated test catches the stated regression and that restoration fixes it. It does **not** prove that no other behavior is affected or that this is the only required test. A baseline graph correctly reads `UNKNOWN` for overall risk after a working-tree edit; individual diff and call edges keep their evidence attribution.

## Proof 1 — FastAPI response serialization

| Item | Observed result |
| --- | --- |
| Source | [FastAPI](https://github.com/fastapi/fastapi) `4ef68e8` |
| Intentional edit | `fastapi/routing.py`: `serialize_response` changed from `if field:` to `if False:`, disabling response-model serialization. |
| CodeSlicer found | Changed method `serialize_response` (line 301), then `serialize_response → app` (exact `CALLS`, line 727) → `APIRoute.handle` (exact `CALLS`, line 1279). |
| Target test | `python -m pytest -q tests/test_custom_schema_fields.py -k test_response` |
| Baseline → broken → restored | exit `0` (3.37 s) → exit `1` (3.08 s) → exit `0` (2.33 s) |

Disabling serialization breaks the response-model contract; restoring only that source expression makes the same API test pass again. The JSON records the symbol, chain, file:line, edge source and confidence.

## Proof 2 — Gin XML binding

| Item | Observed result |
| --- | --- |
| Source | [Gin](https://github.com/gin-gonic/gin) `34dac20` |
| Intentional edit | `context.go`: `(*Context).BindXML` changed from `binding.XML` to `binding.JSON`. |
| CodeSlicer found | Changed method `gin.Context.BindXML` (line 791); direct typed-receiver callers `Render`, `Negotiate`, `File`, plus bounded transitive `JSON`. |
| Target test | `go test . -run ^TestContextBindWithXML$` |
| Baseline → broken → restored | exit `0` (11.63 s) → exit `1` (5.92 s) → exit `0` (0.71 s) |

The broken code parses XML as JSON, so the real Gin test fails. Reverting only that expression makes the same test pass. This is a behavior-level proof, not a source-similarity claim.

## What this run changed

The proof corpus exposed a real bug: `--scope .` was treated as a literal `./` prefix, while Git paths are repository-relative. It silently dropped changed files and produced false `0 impacts`. The root scope is now normalized and has a regression test.

The report also exposes a remaining gap: automatic test recommendations were empty in both proof cases. The commands above are declared test oracles in the manifest, not falsely presented as automatic recommendations.

## Throughput and controls

All six mechanical gates passed: pinned revision, non-empty cold graph, warm cache hit, historical review, comment-only control and language detection. Historical upstream diffs are mostly docs/dependency edits; they are controls, not advertised as behavioral proof.

| Project | Pin | Cold / warm | Meaning |
| --- | --- | ---: | --- |
| [FastAPI](https://github.com/fastapi/fastapi) | `4ef68e8` | 67.01 s / 12.39 s | 3,099 files; proof above exercises a real request-handler path. |
| [Gin](https://github.com/gin-gonic/gin) | `34dac20` | 12.09 s / 3.37 s | 119 files; proof above exercises a real public API method. |
| [Express](https://github.com/expressjs/express) | `a371447` | 9.49 s / 2.46 s | 202 files; front-end inventory and cache validated. |
| [Cruxa](https://github.com/contr4s/Cruxa) | `13ff4a0` | 20.77 s / 2.94 s | C# remains `UNKNOWN` when cross-file closure is not proven. |

Project dependencies were not installed for throughput controls. The two proof commands are the explicit exception: they execute real target tests in disposable copies.

## Reproduce

```powershell
$env:PYTHONPATH = "src"
python scripts/run_real_project_benchmarks.py `
  --output docs/benchmarks/local-real-project-validation.json

python scripts/run_real_project_benchmarks.py `
  --source-root C:\corpora\codeslicer-real-projects `
  --output docs/benchmarks/local-real-project-validation.json
```

The manifest contains public pins and reversible proof cases. The runner uses argv commands (no shell interpolation), emits compact evidence without local paths, and measures this Windows 10 x64 / Python 3.11.9 run only.
