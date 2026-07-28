# C# external golden

Indexer: `scip-dotnet@0.2.14`.

Materialized artifact SHA-256: `824ed7793b3ac8d037105092fcb949bc024390aedbd8e27945da4513e293fac8`.

Run explicitly from the fixture project. This requires a local .NET SDK and
the local tool install; neither is performed by CodeSlicer:

```powershell
Set-Location tests/fixtures/scip/golden/csharp/project
dotnet tool install --global scip-dotnet --version 0.2.14
scip-dotnet index Golden.csproj --allow-global-symbol-definitions --exclude obj/**
Get-FileHash .\index.scip -Algorithm SHA256
```

Set `status` to `materialized` and record the SHA-256 in `manifest.json`. The
embedded SCIP metadata reports `0.1.0-SNAPSHOT` although the installed tool
package is pinned to `0.2.14`. Expected evidence is `IClock`, its
`Now` method, `SystemClock` implementing the interface, and `ReadNow` calling
the method. The project contains an emoji before a target occurrence to
exercise .NET/SCIP UTF-16 offsets. With `scip-dotnet 0.2.14`, the official
SCIP CLI currently reports one upstream diagnostic for the global namespace
occurrence that has no matching `SymbolInformation`; the artifact is kept
unchanged and this limitation is recorded in `manifest.json`. The command
follows the official `scip-dotnet` installation and `scip-dotnet index`
instructions.
