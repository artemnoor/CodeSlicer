# CodeSlicer for VS Code

CodeSlicer helps answer one practical question before merge: what do these changes affect, why, and what should I test?

This extension is a separate TypeScript package in the CodeSlicer repository. It calls the local `codeslicer` CLI and renders its canonical evidence, risk, impact, and test-plan report. It does not contain a second analyzer.

## Local review workflow

Open a trusted workspace, open the CodeSlicer activity-bar view, then choose **Review current changes**. The first screen explains that source code stays on the computer, analysis needs no AI or API key, and no process runs before an explicit action.

The view has five sections:

- **Check** — review source, runtime status, and verified comparison branch.
- **Result** — bounded affected areas and clickable evidence locations.
- **Tests** — safe argv test suggestions; every test asks for a separate confirmation.
- **Architecture** — an optional, separate Graphify view.
- **Settings** — custom executable and other advanced options.

For local review the extension verifies the `origin/HEAD` branch when possible. If it cannot establish one safe base, it lists verified `main`, `master`, `develop`, or `trunk` candidates for the developer to choose. It never assumes that `main` is correct.

Advanced source modes (compare refs or a diff file) are represented in the core contract. GitHub Pull Request review is visible as a future mode but makes no network call in this release.

Use **CodeSlicer: Compare with base branch** or **CodeSlicer: Review a diff file** from the Command Palette for those advanced local sources. The extension retains the ten most recent report summaries in VS Code workspace state; reports stay local to the workspace.

## Runtime and privacy

The normal runtime location is VS Code global storage. Automatic installation is intentionally unavailable until CodeSlicer publishes a signed runtime artifact and verification manifest. Until then, the existing local `.venv` flow still works, and **Settings → Choose an existing executable** remains available; the extension validates either choice locally before use.

There is no GitHub PAT setting in this extension. **CodeSlicer: Sign in to GitHub (optional)** uses VS Code Authentication/OAuth only after the developer selects it; it currently only establishes a session and makes no GitHub API request. Any future PR review, check, or comment will remain an explicit action. Local review never uploads code and never uses a token.

Graphify is an optional architecture engine. Its graph, communities, and inferred links do not contribute to CodeSlicer risk, impact ranking, or canonical evidence.

## Develop and package

```powershell
cd extensions/vscode
npm ci
npm test
```

Open `extensions/vscode` in VS Code and press `F5` to start an Extension Development Host. Activation does not analyze, run tests, start a daemon, install a runtime, or run Graphify.

Create the VSIX with:

```powershell
npm run package
```

The package excludes the Python repository, virtual environments, `node_modules`, graphs, `.impact_engine`, `.codeslicer`, caches, tokens, and test artifacts.
