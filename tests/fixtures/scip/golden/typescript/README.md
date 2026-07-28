# TypeScript external golden

Indexer: `@sourcegraph/scip-typescript@0.3.16`.

Materialized artifact SHA-256: `52267253c85dd2bd0aa1d9b966956e23b6537327fd80768de3aa14fd8dd57dc8`.

From the repository root, run this explicitly (it may use the user's local
package cache; CodeSlicer never runs it automatically):

```powershell
Set-Location tests/fixtures/scip/golden/typescript/project
npm install --ignore-scripts --no-package-lock
npm exec --no -- @sourcegraph/scip-typescript@0.3.16 index
Get-FileHash .\index.scip -Algorithm SHA256
```

Set `status` to `materialized` and copy the printed hash into `manifest.json` as `artifact_sha256`. Expected
evidence is a `Greeter` class, `greet` definition/reference, and a
`useGreeting` reference in two documents. The source includes an emoji before
the target range to exercise SCIP's UTF-16 position encoding; a wrong consumer
must remain unresolved rather than confirm a shifted range.

Expected: definitions `Greeter`, `greet`, and `useGreeting`; references to
`greet`/`useGreeting`; no interface implementations in this fixture. The
command is based on the official scip-typescript quick-start (`scip-typescript index`).
