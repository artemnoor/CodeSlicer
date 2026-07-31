# CodeSlicer for VS Code

CodeSlicer helps answer one practical question before merge: what do these changes affect, why, and what should I test?

This extension is a separate TypeScript package in the CodeSlicer repository. It calls the local `codeslicer` CLI and renders its canonical evidence, risk, impact, and test-plan report. It does not contain a second analyzer.

## Local review workflow

Open a trusted workspace, open the CodeSlicer activity-bar view, then choose **Review current changes**. The first screen explains that source code stays on the computer, analysis needs no AI or API key, and no process runs before an explicit action.

The view keeps the normal first-run path short and exposes the detail only when it is needed:

- **Start** — install CodeSlicer once, then use **Start local server**, **Show code graph**, or **Show Git branches**. The server binds only to the configured loopback URL. It does not open a browser until **Open Local Hub** is explicitly selected.
- **Check** — review source, runtime status, and verified comparison branch.
- **Result** — bounded affected areas and clickable evidence locations.
- **Tests** — safe argv test suggestions; every test asks for a separate confirmation.
- **Code graph** — a compact visual preview of the canonical local CodeSlicer graph. If no graph exists yet, the explicit action analyzes the workspace first.
- **Git branches** — a local timeline of recent commits across all local branches.
- **Architecture** — an optional, separate Graphify view. **Download and set up Graphify** asks for confirmation before installing the official `graphifyy` Python package; **Build Graphify map** runs its local `graphify extract <project> --code-only` command.
- **Settings** — custom executable and other advanced options.

IDE skills, Graphify, comparison, and GitHub PR review are optional advanced actions; they are not part of the first-run path.

## Interactive demo

**Start → Start guided tour** is an in-product, six-step simulation. It visibly switches through the server, review, result, code graph, Git branch, and optional architecture tabs without downloading files, running the CLI, or changing the workspace. The guide is safe to run at any time.

For local review the extension verifies the `origin/HEAD` branch when possible. If it cannot establish one safe base, it lists verified `main`, `master`, `develop`, or `trunk` candidates for the developer to choose. It never assumes that `main` is correct.

Advanced source modes (compare refs or a diff file) are represented in the core contract. GitHub Pull Request review is available as an explicit OAuth flow: after you supply a canonical PR URL and confirm sign-in, the extension sends two read-only GitHub REST requests (metadata and diff), saves the diff only in VS Code global storage, then runs the local CLI. It never uploads source code, creates checks, or posts comments.

Use **CodeSlicer: Compare with base branch** or **CodeSlicer: Review a diff file** from the Command Palette for those advanced local sources. The extension retains the ten most recent report summaries in VS Code workspace state; reports stay local to the workspace.

## Runtime and privacy

**Start → Install CodeSlicer** is the standard Windows path. One explicit click downloads the official CodeSlicer ZIP into VS Code private storage, extracts it, creates a local `.venv`, and configures the resulting `codeslicer.exe` automatically. No browser download folder, destination picker, or manual executable path is required. **Choose an existing executable** remains available only as an advanced option.

After CodeSlicer is configured, **Settings → Choose IDE and skills** opens `codeslicer agent install` in the integrated PowerShell terminal after a second confirmation. It uses the existing interactive IDE chooser and changes only selected integrations; the installer creates a side-by-side backup before editing an existing MCP configuration.

There is no GitHub PAT setting in this extension. **CodeSlicer: Review GitHub pull request (optional)** uses VS Code Authentication/OAuth only after the developer selects it. Any future check or comment will remain a separate explicit action. Local review never uploads code and never stores a token.

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
