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

1. Open the CodeSlicer view in the Activity Bar.
2. Set `codeslicer.executable` if discovery does not find `<workspace>/.venv/Scripts/codeslicer.exe`.
3. Choose **Review current changes**.

The default base branch is local `main`. Set `codeslicer.baseRef` when your team uses another branch. The extension checks that the base exists locally before it starts a review.

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
