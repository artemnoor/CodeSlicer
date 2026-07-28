# Security / SBOM Evidence Adapters

CodeSlicer can import already exported local security reports as optional
`SECURITY_FINDING` overlays. Imports are explicit and accept only absolute
local JSON paths. Only a sanitized normalized overlay is stored in
`.codeslicer/artifacts/`; the original report is never copied by CodeSlicer and
remains at the user-selected local path. The canonical `.impact_engine` graph
is not changed.

| Adapter | Format | Status | Evidence |
| --- | --- | --- | --- |
| `cyclonedx` | CycloneDX JSON 1.x | supported | components, purl/name/version, dependencies, licenses, vulnerabilities |
| `spdx` | SPDX JSON 2.x | supported | packages, purl/name/version, licenses, dependencies and lockfile hints |
| `sarif` | SARIF 2.1.0 JSON | supported | rule ID, severity, safe source location and complete range |

Examples:

```powershell
impact-engine adapters cyclonedx import C:\project C:\reports\bom.json
impact-engine adapters cyclonedx enable C:\project
impact-engine adapters cyclonedx status C:\project --json

impact-engine adapters spdx import C:\project C:\reports\sbom.spdx.json
impact-engine adapters sarif import C:\project C:\reports\scan.sarif.json
```

Mapping is deliberately evidence-gated:

- `confirmed`: exact ecosystem + package + version + manifest/lockfile, or
  exact SARIF file + complete range + rule ID;
- `likely`: package-name-only, resolved version missing, or a file match without
  complete SARIF rule/range evidence;
- `unresolved`: ambiguous ecosystem/package candidates, broken or incomplete
  report data, and relationships without a precise target.

CycloneDX/SPDX describe software inventory and dependency/license facts;
SARIF describes findings and source locations. These overlays are distinct from
the static CodeSlicer graph, SCIP/LSP semantic evidence, Boundary contracts,
and OTel runtime observations. Security evidence never changes canonical graph
edges, Review risk, ranking, or test recommendations.

Privacy boundary:

- no npm audit, pip-audit, `dotnet list package`, scanner, advisory lookup,
  GitHub/OSV/NVD request, or network connection is made;
- report paths, tool metadata, IDs, severity, package identity, licenses, and
  safe file/range pointers are retained locally;
- secrets, credentialed URLs, raw SARIF messages, full descriptions, and
  confidential properties are redacted;
- malformed, unsupported, oversized, stale, or partial reports produce visible
  diagnostics rather than a security claim.

Limits are bounded by a 16 MiB report and 50,000 parsed components/results.
Generated/vendor/node_modules paths are marked excluded from Review entities.
“No finding” never means “secure”, and CodeSlicer does not provide remediation
advice without local evidence.
