# CycloneDX SBOM Adapter

Imports an existing local CycloneDX JSON BOM only after an explicit action.
It records bounded component, dependency, license, and vulnerability evidence
under `.codeslicer`; it never runs a scanner, downloads advisories, or uploads
project data. Exact ecosystem + package + version + manifest/lockfile evidence
can be confirmed; weaker package matches remain likely or unresolved.
