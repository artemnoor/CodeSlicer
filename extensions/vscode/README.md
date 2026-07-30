# CodeSlicer Impact Cockpit (MVP)

This is a standalone VS Code extension package inside the CodeSlicer repository. It is a local-first cockpit for the installed `codeslicer` CLI; it does not embed, copy, or replace the Python analysis engine.

It reviews the local Git diff against a local base branch (default `main`) and presents the canonical CodeSlicer risk, bounded affected entities, evidence chains, recommended tests, coverage limitations, and graph freshness. GitHub metadata, comments, checks, OAuth, PATs, and publishing are deliberately outside this MVP.

Graphify remains a separate optional architecture engine. The extension never downloads, clones, or starts it. If an existing Graphify graph is present at `.codeslicer/artifacts/graphify/graphify-out/graph.json`, the cockpit offers **Open Graphify in Local Hub**; it never mixes that graph into canonical CodeSlicer risk or evidence.

## Run in an Extension Development Host

```powershell
cd extensions/vscode
npm ci
npm run compile
```

Open `extensions/vscode` in VS Code and press `F5` to launch an Extension Development Host. Open the CodeSlicer view from the Activity Bar, set `codeslicer.executable` if discovery does not find `<workspace>/.venv/Scripts/codeslicer.exe`, then choose **Review current changes**.

The extension never starts a process at activation. Each CLI operation requires an explicit command or button, is blocked in an untrusted workspace, runs without a shell, and writes command, cwd, stdout, stderr, and failures to the `CodeSlicer` Output channel.

## Local PR review

`CodeSlicer: Review current changes` verifies the local base ref, then runs the installed executable with `review <workspace> --base <base> --run-tests none --json`. The default base is local `main`; change `codeslicer.baseRef` when needed. It only analyzes a local Git diff and never reads GitHub PR information.

Recommended tests come from the review projection but are not executed during review. Running one requires a separate modal confirmation and only accepts a safe argv array supplied by CodeSlicer; shell interpreters and command strings are rejected.

For full graph details, start Local Hub yourself:

```powershell
impact-engine-local-api --default-project C:\path\to\project
```

Then choose **Open Local Hub** (default `http://127.0.0.1:8001/`). The extension opens only loopback URLs and does not start the service.

## Package a local VSIX

```powershell
cd extensions/vscode
npm ci
npm run package
```

The packaging configuration and `.vscodeignore` exclude the Python repository, virtual environments, `node_modules`, canonical/Graphify artifacts, `.impact_engine`, `.codeslicer`, caches, logs, test output, and VSIX files.

Future optional work can add GitHub integration, CI status reporting, PR comments, Marketplace publishing, and richer editor navigation. This MVP uses no GitHub token.
