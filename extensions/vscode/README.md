# CodeSlicer for VS Code

CodeSlicer is local-first. The TypeScript package supplies the cockpit while the canonical Python Core is bundled as a separate process inside each platform-specific VSIX. Normal users do not install Python, pip, a virtualenv, source code, Graphify, or an executable.

Install the matching VSIX, open a trusted project, and select **Review current changes**. The extension uses argv-only spawning with `shell: false` and logs argv, cwd, stdout, stderr, and exit status. No process runs during activation.

## Platform packages

| Target | Build method |
| --- | --- |
| `win32-x64`, `win32-arm64` | native Windows runner |
| `darwin-x64`, `darwin-arm64` | native macOS runner |
| `linux-x64`, `linux-arm64` | native Linux runner |

VS Code selects platform-specific packages created with `vsce --target`. The runtime resolves in the workspace extension host, so WSL, SSH, Dev Containers, and Codespaces need the matching VSIX installed in that remote window. Unsupported hosts get a diagnostic; CodeSlicer never downloads a substitute.

Each package contains one `runtime/<target>/bin/codeslicer` executable. It has explicit CLI and `local-api` modes, avoiding a duplicate embedded Python runtime while preserving the Local Hub. The manifest carries version/platform/architecture/SHA-256 data and embedded-runtime notices/licenses; the extension verifies every declared file before execution, and an invalid checksum, missing file, or unsafe manifest path blocks the runtime.

## Development and packaging

```powershell
cd extensions/vscode
npm ci
npm test
# Press F5 here for an Extension Development Host.
npm run package
```

`scripts/build_bundled_runtime.py` refuses cross-platform builds. It uses PyInstaller on a native runner to package the current Core, support packs, language plugins, Tree-sitter dependencies, and private Python runtime. Install `pyinstaller` in the build environment. CI creates non-Windows artifacts. Inspect generated VSIX files with `Expand-Archive` or `unzip -l`.

The VSIX excludes the source repository, `.venv`, `node_modules`, caches, `.impact_engine`, Graphify outputs, tests, and secrets.

## Cockpit workflow

The webview keeps the normal path simple:

1. **Review** — choose working tree, staged changes, branch comparison, a local patch, or optional GitHub PR.
2. **Results** — risk, reasons, affected entities, and evidence.
3. **Tests** — recommendations; every real test requires a new modal confirmation.
4. **Technologies** — built-in language coverage, graph freshness, and optional-pack status.
5. **History** — the last local review summaries in workspace state.
6. **Code** — a bounded canonical CodeSlicer slice; Graphify remains an explicitly connected, separate optional engine.
7. **Git** — a separate branch tree with current/upstream state, remotes, recent commits, branch creation/switching, and a push preflight.

The interactive guide only switches these real tabs. It does not invoke Git,
the runtime, tests, or network requests.

## Optional language packs

Core language coverage is bundled for offline use. Additional language packs
are deliberately unavailable until CodeSlicer publishes a signed registry and
verification key. The extension does not contain a guessed endpoint or a
pretend download action. A future registry must provide a target-specific,
versioned manifest plus SHA-256 and signature verification, atomic installation
and rollback; until then the Technologies screen reports the honest offline
state.

## Product boundaries

The cockpit supports analysis, working-tree/compare/diff review, risk/evidence/test recommendations, confirmed test execution, selected-symbol inspect, local history, source navigation, and the canonical architecture slice. Local Hub opens only after an explicit user action and listens on loopback.

Graphify is optional and separate: CodeSlicer never downloads or installs it, and its data does not affect canonical evidence or ranking. Local Git review needs no GitHub token.

## Git cockpit and GitHub access

The Git tab is intentionally explicit: it reads the local branch tree only after you select **Refresh tree**; create/switch branch and add-remote actions are each confirmed. Before a push you select the exact local source branch, remote, and destination branch. The extension shows ahead/behind status and blocks a likely non-fast-forward push. A second modal confirmation is required to push, and force-push is never offered.

Push uses the Git credentials already configured for your machine (Git Credential Manager or SSH). CodeSlicer does not place a token into a remote URL, shell command, Output log, or workspace settings. The optional **Store GitHub token** control writes it only to VS Code Secret Storage for future GitHub API functionality; today GitHub PR preparation uses explicit VS Code OAuth and read-only API calls. Publishing PR comments/checks is not implemented.
