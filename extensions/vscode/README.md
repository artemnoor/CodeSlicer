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

Each package contains `runtime/<target>/bin/{codeslicer,impact-engine-local-api}`, a manifest with version/platform/architecture/SHA-256 data, and embedded-runtime notices/licenses. The extension verifies its launcher checksum before execution.

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

## Product boundaries

The cockpit supports analysis, working-tree/compare/diff review, risk/evidence/test recommendations, confirmed test execution, selected-symbol inspect, local history, source navigation, and the canonical architecture slice. Local Hub opens only after an explicit user action and listens on loopback.

Graphify is optional and separate: CodeSlicer never downloads or installs it, and its data does not affect canonical evidence or ranking. Local Git review needs no GitHub token. GitHub PR preparation is advanced and read-only; publishing comments/checks is not implemented.
