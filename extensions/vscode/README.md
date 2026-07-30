# CodeSlicer Impact Cockpit

Know the blast radius before you ask for review.

CodeSlicer is a local-first cockpit for the code you have just changed. It reads your local Git diff and the canonical evidence graph produced by CodeSlicer, then puts the useful part in front of you: risk, affected routes and services, evidence chains, test candidates, graph freshness, and the limits of what can be proven.

No GitHub sign-in. No PR metadata. No background scan when VS Code starts. You choose when CodeSlicer runs.

## What you get before merge

- A bounded risk card with the reason behind the level, not a mystery score.
- The entities closest to the change, including routes, services, frontend clients, and tests when CodeSlicer has evidence for them.
- A compact impact mini-map. Click a node to inspect its evidence, provenance, file, and line.
- Test recommendations from the review projection. Nothing runs until you confirm a safe command.
- Warnings about stale graphs, limited language coverage, and missing proof. Silence is not presented as certainty.

The review always works from a local Git diff. It does not read GitHub comments, checks, or pull-request metadata.

## Start a review

1. Open the CodeSlicer view in the Activity Bar and use the **Current** tab.
2. Follow the three cards: check the CodeSlicer executable, choose the local base branch, then select **Review current changes**.
3. Use the **Impact** tab for the bounded evidence map and affected entities. Use **Tests & limits** for recommended tests and explicit coverage limits.

### Take the interactive tour

Select **How it works** in the cockpit header at any time. The short guided tour highlights each of the three review steps, then switches to **Impact** and **Tests & limits** to explain what appears after a review. It never configures CodeSlicer, starts an analysis, or runs a test: those actions always require your own click. Use **Skip tour**, **Back**, or `Esc` to leave it.

The cockpit has Russian and English interfaces. Choose the language in the upper-right selector, or set `codeslicer.uiLanguage` to `auto`, `ru`, or `en` in VS Code settings.

### Download CodeSlicer and Graphify

In Step 1, choose **Download CodeSlicer** (or run **CodeSlicer: Download CodeSlicer and Graphify**). A separate VS Code tab opens with two clearly separated download buttons:

1. **Download CodeSlicer** opens the official CodeSlicer source ZIP archive. Extract it, follow the repository README to create a virtual environment and install CodeSlicer, then return to the tab and select **Already downloaded? Choose CodeSlicer**.
2. **Download Graphify** is optional and opens Graphify's official source ZIP archive. Graphify stays a separate architecture tool; after generating its `graph.json`, use **Choose graph.json** in the sidebar to connect it.

The download page does not run commands, install packages, request tokens, or modify the workspace. Each download is an explicit button click.

## Connections

The compact **Connections** cards at the top make optional setup visible without hiding the local review flow.

- **GitHub token** — select **Add or replace token** to enter an optional token in VS Code's native password prompt. The token is stored only in VS Code Secret Storage, never in `settings.json`, the workspace, logs, or the VSIX. Current local review does not use the token or call GitHub; a future explicit PR-integration feature may use it.
- **Graphify** — select **Choose graph.json** and point to an already-created local Graphify `graph.json`. CodeSlicer will not download, clone, or run Graphify. The selected architecture graph stays separate from canonical CodeSlicer evidence and risk.

The default base branch is local `main`. Set `codeslicer.baseRef` when your team uses another branch. The extension checks that the base exists locally before it starts a review.

### Do I need a GitHub token?

No. Local review does not call GitHub, GitHub Actions, or the GitHub API. It compares local Git branches and runs the installed local `codeslicer` executable only, so there is no token to paste or store. GitHub integration remains a separate future capability.

Every command runs with direct argv, never through a shell. In an untrusted workspace, CodeSlicer will not start a process.

## Full detail stays in Local Hub

The sidebar is deliberately small. For the full canonical graph, open a Local Hub you have already started:

```powershell
impact-engine-local-api --default-project C:\path\to\project
```

Then choose **Open Local Hub**. The extension opens loopback URLs only and never starts the service for you.

Graphify remains a separate optional architecture engine. If its local graph already exists, CodeSlicer offers **Open Graphify in Local Hub**. It does not blend Graphify data into CodeSlicer risk, ranking, or evidence.

## Privacy and control

The extension talks to the local `codeslicer` executable you select. It does not contain another analyzer, upload source code, require a GitHub token, or connect to GitHub for local review. Command, working directory, stdout, stderr, and errors are available in the `CodeSlicer` Output channel.

## Develop or package

```powershell
cd extensions/vscode
npm ci
npm run compile
```

Open `extensions/vscode` in VS Code and press `F5` to launch an Extension Development Host.

To create a VSIX:

```powershell
npm run package
```

The package excludes the Python repository, virtual environments, `node_modules`, canonical and Graphify artifacts, `.impact_engine`, `.codeslicer`, caches, test output, and local VSIX archives.

## Feedback

Issues and feature requests belong in the [CodeSlicer repository](https://github.com/artemnoor/CodeSlicer/issues).
