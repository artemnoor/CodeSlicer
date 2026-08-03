import * as vscode from "vscode";
import { ChildProcessWithoutNullStreams, spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { createHash } from "node:crypto";
import { buildAnalyzeArgs, buildReviewArgs, formatCommand, runProcess, safeTestCommand } from "./cli";
import { parseReviewJson, withReview } from "./review";
import { isSafeRef } from "./runtime";
import { CodeSlicerRuntimeManager } from "./runtime-manager";
import { detectBaseSelection } from "./base";
import { parseJsonLineProgress } from "./progress";
import { GitHubReviewService } from "./github";
import { CockpitState, INITIAL_STATE, ProjectState, ReviewHistoryEntry, ReviewState, ReviewSourceMode, TestRecommendation, UiLanguage } from "./types";
import { renderCockpit, renderReviewReport } from "./webview";
import { buildPushArgs, isPlausibleGitRemote, parseGitBranches, parseGitRemotes, PushPreview } from "./git";

const OUTPUT = vscode.window.createOutputChannel("CodeSlicer");
const graphPath = (root: string) => join(root, ".impact_engine", "graph.json");
const graphifyPath = (root: string, configured: string) => configured.trim() || join(root, ".codeslicer", "artifacts", "graphify", "graphify-out", "graph.json");

class CockpitProvider implements vscode.WebviewViewProvider {
  private view?: vscode.WebviewView;
  private reviewPanel?: vscode.WebviewPanel;
  private state: CockpitState = structuredClone(INITIAL_STATE);
  private tests: TestRecommendation[] = [];
  private selectedLanguage?: "ru" | "en";
  private serverProcess?: ChildProcessWithoutNullStreams;
  private readonly runtime: CodeSlicerRuntimeManager;
  private readonly github = new GitHubReviewService();
  private readonly status: vscode.StatusBarItem;
  /** A guided push must use the real Git result rather than infer it from refreshed state. */
  private lastPushOutcome: "success" | "error" | "cancelled" | undefined;

  constructor(private readonly context: vscode.ExtensionContext) {
    this.runtime = new CodeSlicerRuntimeManager(context.extensionPath);
    this.status = vscode.window.createStatusBarItem("codeslicer.review", vscode.StatusBarAlignment.Left, 20);
    this.status.command = "codeslicer.reviewCurrentChanges";
    this.status.text = "$(shield) CodeSlicer: Review changes";
    this.status.tooltip = "Review current local Git changes with CodeSlicer";
    this.status.show();
    context.subscriptions.push(this.status);
    context.subscriptions.push({ dispose: () => this.serverProcess?.kill() });
    const saved = context.workspaceState.get<ReviewState>("codeslicer.lastReview");
    const history = context.workspaceState.get<ReviewHistoryEntry[]>("codeslicer.reviewHistory") || [];
    const reviewSource = context.workspaceState.get<CockpitState["reviewSource"]>("codeslicer.reviewSource") || INITIAL_STATE.reviewSource;
    this.state = { ...this.state, review: saved || this.state.review, history, reviewSource };
  }

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    view.webview.options = { enableScripts: true };
    view.webview.onDidReceiveMessage(message => this.onMessage(message));
    this.render();
    void this.refreshWorkspaceReadiness();
    // The initial render stays instant, then validate the immutable bundled
    // runtime in the background.  A fresh profile therefore moves from
    // “Preparing runtime…” to Ready without a second click or Git activity.
    void this.warmRuntimeReadiness();
  }

  private workspace(): string | undefined {
    return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  }

  /** Read-only first-run check. It deliberately does not invoke Git or CodeSlicer. */
  private async refreshWorkspaceReadiness(): Promise<void> {
    const root = this.workspace();
    if (!root) return;
    try {
      const ignored = new Set([".git", ".vscode", ".impact_engine", ".codeslicer", ".venv", "venv", "env", "node_modules", "__pycache__"]);
      const entries = await readdir(root, { withFileTypes: true });
      const readiness = entries.some(entry => !ignored.has(entry.name)) ? "project" : "empty";
      const hasGitDirectory = entries.some(entry => entry.name === ".git");
      this.state = { ...this.state, project: { ...this.state.project, workspace: root, readiness, gitStatus: readiness === "empty" ? "unknown" : hasGitDirectory ? "ready" : "missing", gitMessage: readiness === "empty" ? "Open or create a project first." : hasGitDirectory ? "Git repository detected; refresh to read branches." : "Git is not initialized in this folder." } };
      this.render();
    } catch {
      this.state = { ...this.state, project: { ...this.state.project, workspace: root, readiness: "unknown" } };
      this.render();
    }
  }

  private async selectWorkspace(): Promise<string | undefined> {
    const folders = vscode.workspace.workspaceFolders || [];
    if (folders.length < 2) return folders[0]?.uri.fsPath;
    const picked = await vscode.window.showQuickPick(folders.map(folder => ({ label: folder.name, description: folder.uri.fsPath, folder })), { title: "Choose a workspace folder for this review", ignoreFocusOut: true });
    return picked?.folder.uri.fsPath;
  }

  private config<T>(name: string): T {
    return vscode.workspace.getConfiguration("codeslicer").get<T>(name)!;
  }

  private language(): "ru" | "en" {
    if (this.selectedLanguage) return this.selectedLanguage;
    const preference = this.config<UiLanguage>("uiLanguage");
    if (preference === "ru" || preference === "en") return preference;
    return vscode.env.language.toLowerCase().startsWith("ru") ? "ru" : "en";
  }

  private render(): void {
    if (this.view) this.view.webview.html = renderCockpit(this.state, this.language());
    if (this.reviewPanel) this.reviewPanel.webview.html = renderReviewReport(this.state, this.language());
  }

  /** Open the concise review answer where VS Code has room to read it. */
  private showReviewReport(): void {
    if (!this.reviewPanel) {
      this.reviewPanel = vscode.window.createWebviewPanel(
        "codeslicer.reviewReport",
        "CodeSlicer: Review result",
        { viewColumn: vscode.ViewColumn.Active, preserveFocus: false },
        { enableScripts: true, retainContextWhenHidden: true },
      );
      this.reviewPanel.onDidDispose(() => { this.reviewPanel = undefined; });
      this.reviewPanel.webview.onDidReceiveMessage(message => this.onMessage(message));
    }
    this.reviewPanel.webview.html = renderReviewReport(this.state, this.language());
    this.reviewPanel.reveal(vscode.ViewColumn.Active, false);
  }

  private log(result: { command: string[]; cwd: string; exitCode: number; stdout: string; stderr: string }): void {
    OUTPUT.appendLine(`$ ${formatCommand(result.command)}`);
    OUTPUT.appendLine(`cwd: ${result.cwd}`);
    if (result.stdout) OUTPUT.appendLine(result.stdout);
    if (result.stderr) OUTPUT.appendLine(result.stderr);
    OUTPUT.appendLine(`exit code: ${result.exitCode}\n`);
  }

  private async needWorkspace(): Promise<string | undefined> {
    const root = await this.selectWorkspace();
    if (!root) await vscode.window.showErrorMessage("CodeSlicer needs an opened workspace folder.");
    return root;
  }

  private async trusted(): Promise<boolean> {
    if (vscode.workspace.isTrusted) return true;
    await vscode.window.showWarningMessage("CodeSlicer does not run CLI commands in an untrusted workspace. Trust the workspace first.");
    return false;
  }

  private localHubUrl(): URL | undefined {
    try {
      const url = new URL(this.config<string>("localHubUrl"));
      if (!["127.0.0.1", "localhost", "::1"].includes(url.hostname)) throw new Error();
      return url;
    } catch {
      void vscode.window.showErrorMessage("codeslicer.localHubUrl must be a loopback URL, for example http://127.0.0.1:8001/.");
      return undefined;
    }
  }

  private setServer(status: CockpitState["server"]["status"], message: string, url?: string): void {
    this.state = { ...this.state, server: { status, message, url: url || this.state.server.url } };
    this.render();
  }

  private async warmRuntimeReadiness(): Promise<void> {
    const root = this.workspace();
    if (!root) return;
    const runtime = await this.runtime.validate(root, this.config<string>("executable"));
    this.state = { ...this.state, runtime };
    this.render();
  }

  /** Surface the analyzer's real JSONL percent in the Cockpit, not only in a transient toast. */
  private setAnalysisProgress(status: CockpitState["analysis"]["status"], percent: number, message = "", details: Partial<CockpitState["analysis"]> = {}): void {
    const nextPercent = Math.max(0, Math.min(100, Math.round(percent)));
    const current = this.state.analysis;
    const next = { ...current, ...details, status, percent: nextPercent, message };
    if (current.status === next.status && current.percent === next.percent && current.message === next.message && current.processed === next.processed && current.total === next.total && current.elapsedSeconds === next.elapsedSeconds && current.etaSeconds === next.etaSeconds) return;
    this.state = { ...this.state, analysis: next };
    this.render();
  }

  private async waitForServer(url: URL): Promise<boolean> {
    const health = new URL("api/health", url).toString();
    for (let attempt = 0; attempt < 20; attempt += 1) {
      try {
        const response = await fetch(health);
        if (response.ok) return true;
      } catch { /* The local process is still starting. */ }
      await new Promise(resolve => setTimeout(resolve, 250));
    }
    return false;
  }

  private async projectState(root: string): Promise<ProjectState> {
    const repository = await runProcess("git", ["rev-parse", "--is-inside-work-tree"], root, 15_000);
    this.log(repository);
    const configuredGraphify = this.config<string>("graphifyGraphPath");
    const architectureGraph = graphifyPath(root, configuredGraphify);
    if (repository.exitCode !== 0 || repository.stdout.trim() !== "true") return {
      workspace: root, readiness: this.state.project.readiness === "unknown" ? "project" : this.state.project.readiness,
      gitStatus: "missing", gitMessage: "Git is not initialized in this folder. Initialize Git to review changes and manage branches.",
      graphStatus: existsSync(graphPath(root)) ? "present" : "missing", freshness: existsSync(graphPath(root)) ? "Graph file found; freshness is verified by Review." : "No .impact_engine/graph.json",
      graphifyAvailable: existsSync(architectureGraph), graphifyPath: architectureGraph
    };
    const branchResult = await runProcess("git", ["branch", "--show-current"], root, 15_000);
    this.log(branchResult);
    const base = await detectBaseSelection(root, this.config<string>("baseRef"));
    return {
      workspace: root,
      readiness: this.state.project.readiness === "unknown" ? "project" : this.state.project.readiness,
      gitStatus: "ready", gitMessage: "Git repository is ready. Nothing is sent until you explicitly confirm a push.",
      branch: branchResult.stdout.trim() || "detached HEAD",
      baseRef: base.base,
      baseCandidates: base.candidates,
      baseStatus: base.status,
      graphStatus: existsSync(graphPath(root)) ? "present" : "missing",
      freshness: existsSync(graphPath(root)) ? "Graph file found; freshness is verified by Review." : "No .impact_engine/graph.json",
      graphifyAvailable: existsSync(architectureGraph),
      graphifyPath: architectureGraph
    };
  }

  async refresh(): Promise<void> {
    const root = await this.needWorkspace();
    if (!root || !await this.trusted()) return;
    this.state = {
      ...this.state,
      runtime: await this.runtime.validate(root, this.config<string>("executable")),
      project: await this.projectState(root),
      integration: { ...this.state.integration, githubTokenConfigured: false }
    };
    this.render();
  }

  async configure(): Promise<void> {
    const root = await this.needWorkspace();
    if (!root) return;
    const found = await this.runtime.discover(this.config<string>("executable"));
    const value = await vscode.window.showInputBox({
      title: "CodeSlicer executable",
      prompt: "Advanced developer fallback: absolute path to an existing codeslicer executable",
      value: this.config<string>("executable") || found || "",
      ignoreFocusOut: true
    });
    if (value === undefined) return;
    await vscode.workspace.getConfiguration("codeslicer").update("executable", value.trim(), vscode.ConfigurationTarget.Global);
    await this.refresh();
  }

  async doctor(): Promise<void> {
    const root = await this.needWorkspace();
    if (!root || !await this.trusted()) return;
    const result = await this.runtime.doctor(root, this.config<string>("executable"));
    if (result.ok) await vscode.window.showInformationMessage("CodeSlicer runtime check completed. See the Output channel for details.");
    else await vscode.window.showWarningMessage(`CodeSlicer runtime check: ${result.diagnostic}`);
  }

  async runtimeAvailability(): Promise<void> {
    await vscode.window.showInformationMessage(this.runtime.installationAvailability());
  }

  /** The tour is a webview-only simulation: it never writes a workspace or starts a process. */
  async downloadCodeSlicer(): Promise<void> { await vscode.window.showInformationMessage(this.runtime.installationAvailability()); }
  async startDemo(): Promise<void> { await this.showDemo(); }

  async showDemo(): Promise<void> {
    await this.view?.webview.postMessage({ type: "showDemo" });
  }

  async applyDemoChange(): Promise<void> { await this.showDemo(); }
  async reviewDemo(): Promise<void> { await this.showDemo(); }
  async testDemo(): Promise<void> { await this.showDemo(); }

  async openOrCreateProject(): Promise<void> {
    const picked = await vscode.window.showOpenDialog({
      title: "Open or create a project folder",
      canSelectFiles: false,
      canSelectFolders: true,
      canSelectMany: false,
      openLabel: "Open project"
    });
    if (picked?.[0]) await vscode.commands.executeCommand("vscode.openFolder", picked[0], false);
  }

  async importFromGit(): Promise<void> {
    const repository = await vscode.window.showInputBox({
      title: "Import project from Git",
      prompt: "Repository URL, for example https://github.com/owner/project.git",
      placeHolder: "https://github.com/owner/project.git",
      ignoreFocusOut: true,
      validateInput: value => /^(https?:\/\/|git@)[^\s]+$/u.test(value.trim()) ? undefined : "Enter an HTTPS URL or an SSH Git address."
    });
    if (!repository) return;
    try {
      // Delegate cloning to VS Code's Git extension. No shell command is built here.
      await vscode.commands.executeCommand("git.clone", repository.trim());
    } catch (error) {
      await vscode.window.showErrorMessage(`VS Code could not start Git import: ${String(error)}`);
    }
  }

  async initializeGit(): Promise<void> {
    const root = await this.needWorkspace();
    if (!root || !await this.trusted()) return;
    const choice = await vscode.window.showWarningMessage("Initialize a new local Git repository in this folder? This does not create a remote or send data anywhere.", { modal: true }, "Initialize Git");
    if (choice !== "Initialize Git") return;
    const result = await runProcess("git", ["init"], root, 30_000);
    this.log(result);
    if (result.exitCode !== 0) await vscode.window.showErrorMessage(result.stderr.trim() || "Git could not initialize this folder.");
    else { await vscode.window.showInformationMessage("Local Git repository initialized. Create your first commit when ready."); await this.refresh(); }
  }

  async setupSkills(): Promise<void> {
    await vscode.window.showInformationMessage("CodeSlicer does not install MCP entries or IDE skills as part of the self-contained VS Code workflow.");
  }

  async configureBaseRef(): Promise<void> {
    const value = await vscode.window.showInputBox({
      title: "CodeSlicer review base branch",
      prompt: "Local branch to compare with, for example main",
      value: this.config<string>("baseRef").trim() || "main",
      ignoreFocusOut: true
    });
    if (value === undefined) return;
    const base = value.trim();
    if (!isSafeRef(base)) {
      await vscode.window.showErrorMessage("Base branch must be a safe local Git ref, for example main or release/1.2.");
      return;
    }
    await vscode.workspace.getConfiguration("codeslicer").update("baseRef", base, vscode.ConfigurationTarget.Workspace);
    const root = this.workspace();
    if (root && vscode.workspace.isTrusted) await this.refresh();
    else {
      this.state = { ...this.state, project: { ...this.state.project, baseRef: base } };
      this.render();
    }
  }

  async configureGraphify(): Promise<void> {
    const picked = await vscode.window.showOpenDialog({
      title: "Choose an existing Graphify graph.json",
      canSelectMany: false,
      canSelectFiles: true,
      canSelectFolders: false,
      filters: { "Graphify graph": ["json"] },
      openLabel: "Use this Graphify graph"
    });
    if (!picked?.[0]) return;
    await vscode.workspace.getConfiguration("codeslicer").update("graphifyGraphPath", picked[0].fsPath, vscode.ConfigurationTarget.Workspace);
    const root = this.workspace();
    if (root && vscode.workspace.isTrusted) await this.refresh();
  }

  async startLocalServer(): Promise<void> {
    const root = await this.needWorkspace();
    if (!root || !await this.trusted()) return;
    const url = this.localHubUrl();
    if (!url) return;
    if (this.serverProcess && this.serverProcess.exitCode === null) {
      this.setServer("ready", "Local server is already running.", url.toString());
      return;
    }
    const executable = await this.executable(root);
    if (!executable) return;
    this.setServer("running", "Starting the local-only server…", url.toString());
    const args = ["local-api", "--host", url.hostname === "localhost" ? "127.0.0.1" : url.hostname, "--port", String(url.port ? Number(url.port) : 80), "--default-project", root];
    const child = spawn(executable, args, { cwd: root, shell: false, windowsHide: true });
    this.serverProcess = child;
    child.stdout.on("data", data => OUTPUT.append(data.toString()));
    child.stderr.on("data", data => OUTPUT.append(data.toString()));
    child.on("error", error => this.setServer("error", `Could not start the local server: ${String(error)}`, url.toString()));
    child.on("close", code => {
      if (this.serverProcess === child) {
        this.serverProcess = undefined;
        if (this.state.server.status === "running") this.setServer("error", `Local server stopped (exit ${code ?? "unknown"}).`, url.toString());
      }
    });
    if (!await this.waitForServer(url)) {
      child.kill();
      this.setServer("error", "The local server did not answer on its loopback URL. See CodeSlicer Output.", url.toString());
      await vscode.window.showErrorMessage("CodeSlicer local server did not start. See CodeSlicer Output.");
      return;
    }
    this.setServer("ready", "Running locally on this computer. No source code is sent to the network.", url.toString());
    await vscode.env.openExternal(vscode.Uri.parse(url.toString()));
  }

  async stopLocalServer(): Promise<void> {
    this.serverProcess?.kill();
    this.serverProcess = undefined;
    this.setServer("idle", "Server stopped.");
  }

  async showCodeGraph(): Promise<void> {
    const root = await this.needWorkspace();
    if (!root) return;
    try {
      const data = JSON.parse(await readFile(graphPath(root), "utf8")) as { nodes?: unknown[]; edges?: unknown[] };
      const rawNodes = Array.isArray(data.nodes) ? data.nodes : [];
      const nodes = rawNodes.slice(0, 32).flatMap(raw => {
        if (!raw || typeof raw !== "object") return [];
        const node = raw as { id?: unknown; name?: unknown; kind?: unknown };
        if (typeof node.id !== "string") return [];
        return [{ id: node.id, label: String(node.name || node.id).slice(0, 48), kind: String(node.kind || "symbol") }];
      });
      const ids = new Set(nodes.map(node => node.id));
      const edges = (Array.isArray(data.edges) ? data.edges : []).slice(0, 120).flatMap(raw => {
        if (!raw || typeof raw !== "object") return [];
        const edge = raw as { from?: unknown; to?: unknown; from_node?: unknown; to_node?: unknown; source?: unknown; target?: unknown };
        const source = String(edge.from || edge.from_node || edge.source || "");
        const target = String(edge.to || edge.to_node || edge.target || "");
        return ids.has(source) && ids.has(target) ? [{ source, target }] : [];
      });
      this.state = { ...this.state, codeGraph: { status: "ready", nodes, edges, totalNodes: rawNodes.length, totalEdges: Array.isArray(data.edges) ? data.edges.length : 0, message: `Showing a readable sample of ${nodes.length} nodes.` } };
      this.render();
    } catch {
      this.state = { ...this.state, codeGraph: { ...this.state.codeGraph, status: "error", message: "No CodeSlicer graph yet. Run Analyze workspace first." } };
      this.render();
    }
  }

  async analyzeAndShowGraph(): Promise<void> {
    const root = await this.needWorkspace();
    if (!root || !await this.trusted()) return;
    if (!existsSync(graphPath(root))) {
      try {
        await this.analyze();
      } catch (error) {
        this.state = { ...this.state, codeGraph: { ...this.state.codeGraph, status: "error", message: `Could not build the code graph: ${String(error)}` } };
        this.render();
        await vscode.window.showErrorMessage(`CodeSlicer could not build the code graph: ${String(error)}`);
        return;
      }
    }
    await this.showCodeGraph();
  }

  async showGitBranches(): Promise<void> {
    const root = await this.needWorkspace();
    if (!root || !await this.trusted()) return;
    const [history, branches, remotes] = await Promise.all([
      runProcess("git", ["log", "--all", "--date-order", "--decorate=short", "--pretty=format:%H%x09%P%x09%D%x09%s", "-n", "40"], root, 30_000),
      runProcess("git", ["for-each-ref", "--format=%(refname:short)%x09%(upstream:short)%x09%(HEAD)%x09%(upstream:trackshort)", "refs/heads"], root, 30_000),
      runProcess("git", ["remote", "-v"], root, 30_000)
    ]);
    [history, branches, remotes].forEach(result => this.log(result));
    if (history.exitCode !== 0 || branches.exitCode !== 0) {
      this.state = { ...this.state, gitGraph: { ...this.state.gitGraph, status: "error", commits: [], branches: [], remotes: [], message: history.stderr.trim() || branches.stderr.trim() || "Git history is unavailable." } };
      this.render();
      return;
    }
    const commits = history.stdout.split(/\r?\n/u).flatMap(line => {
      const [id, parents = "", refs = "", subject = ""] = line.split("\t", 4);
      return id ? [{ id, parents: parents.split(" ").filter(Boolean), refs, subject }] : [];
    });
    const branchItems = parseGitBranches(branches.stdout);
    const remoteItems = remotes.exitCode === 0 ? parseGitRemotes(remotes.stdout) : [];
    const message = remoteItems.length ? `${branchItems.length} local branches · ${remoteItems.length} remotes · ${commits.length} recent commits.` : `${branchItems.length} local branches · no remote is configured yet.`;
    this.state = { ...this.state, gitGraph: { status: "ready", commits, branches: branchItems, remotes: remoteItems, message } };
    this.render();
  }

  async createBranch(): Promise<void> {
    const root = await this.needWorkspace();
    if (!root || !await this.trusted()) return;
    const name = await vscode.window.showInputBox({ title: "Create a new Git branch", prompt: "Branch name, for example feature/payment-review", placeHolder: "feature/my-change", ignoreFocusOut: true });
    if (name === undefined || !name.trim()) return;
    const checked = await runProcess("git", ["check-ref-format", "--branch", name.trim()], root, 15_000);
    this.log(checked);
    if (checked.exitCode !== 0) { await vscode.window.showErrorMessage("This is not a valid Git branch name."); return; }
    const choice = await vscode.window.showWarningMessage(`Create and switch to '${name.trim()}'?`, { modal: true }, "Create branch");
    if (choice !== "Create branch") return;
    const result = await runProcess("git", ["switch", "-c", name.trim()], root, 30_000);
    this.log(result);
    if (result.exitCode !== 0) await vscode.window.showErrorMessage(result.stderr.trim() || "Git could not create this branch.");
    else { await vscode.window.showInformationMessage(`Created and switched to ${name.trim()}.`); await this.refresh(); await this.showGitBranches(); }
  }

  async switchBranch(): Promise<void> {
    const root = await this.needWorkspace();
    if (!root || !await this.trusted()) return;
    if (!this.state.gitGraph.branches.length) await this.showGitBranches();
    const choices = this.state.gitGraph.branches.filter(branch => !branch.current).map(branch => ({ label: branch.name, description: branch.upstream ? `tracks ${branch.upstream} ${branch.tracking || ""}` : "local branch" }));
    const picked = await vscode.window.showQuickPick(choices, { title: "Switch Git branch", placeHolder: "Uncommitted changes can prevent switching" });
    if (!picked) return;
    const result = await runProcess("git", ["switch", picked.label], root, 30_000);
    this.log(result);
    if (result.exitCode !== 0) await vscode.window.showErrorMessage(result.stderr.trim() || "Git could not switch branch. Commit, stash, or resolve conflicting changes first.");
    else { await this.refresh(); await this.showGitBranches(); }
  }

  async addRemote(): Promise<void> {
    const root = await this.needWorkspace();
    if (!root || !await this.trusted()) return;
    const name = await vscode.window.showInputBox({ title: "Add Git remote", prompt: "Remote name", value: "origin", validateInput: value => /^[A-Za-z0-9._-]+$/u.test(value.trim()) ? undefined : "Use letters, numbers, dot, underscore, or hyphen." });
    if (!name) return;
    const url = await vscode.window.showInputBox({ title: "Add Git remote", prompt: "HTTPS or SSH repository address", placeHolder: "https://github.com/owner/repository.git", validateInput: value => isPlausibleGitRemote(value) ? undefined : "Enter an HTTPS or SSH Git URL." });
    if (!url) return;
    const choice = await vscode.window.showWarningMessage(`Add remote '${name.trim()}'?\n${url.trim()}`, { modal: true }, "Add remote");
    if (choice !== "Add remote") return;
    const result = await runProcess("git", ["remote", "add", name.trim(), url.trim()], root, 30_000);
    this.log(result);
    if (result.exitCode !== 0) await vscode.window.showErrorMessage(result.stderr.trim() || "Git could not add this remote.");
    else { await vscode.window.showInformationMessage(`Remote '${name.trim()}' added. No branch was pushed.`); await this.showGitBranches(); }
  }

  private async choosePushTarget(): Promise<{ source: string; remote: string; target: string; setUpstream: boolean } | undefined> {
    const root = await this.needWorkspace();
    if (!root) return undefined;
    if (!this.state.gitGraph.branches.length) await this.showGitBranches();
    const current = this.state.gitGraph.branches.find(branch => branch.current)?.name;
    const source = await vscode.window.showQuickPick(this.state.gitGraph.branches.map(branch => ({ label: branch.name, description: branch.current ? "current branch" : "local branch" })), { title: "Choose branch to push", placeHolder: "Choose a local source branch", canPickMany: false });
    if (!source) return undefined;
    const remote = await vscode.window.showQuickPick(this.state.gitGraph.remotes.map(item => ({ label: item.name, description: item.pushUrl || item.fetchUrl || "remote" })), { title: "Choose destination remote", placeHolder: this.state.gitGraph.remotes.length ? "Choose remote" : "Add a remote first" });
    if (!remote) { if (!this.state.gitGraph.remotes.length) await vscode.window.showWarningMessage("No Git remote is configured. Add one first."); return undefined; }
    const target = await vscode.window.showInputBox({ title: "Choose destination branch", prompt: `Push ${source.label} to this branch on ${remote.label}`, value: source.label === current ? source.label : "", validateInput: value => isSafeRef(value.trim()) ? undefined : "Enter a safe Git branch name." });
    if (!target) return undefined;
    const known = this.state.gitGraph.branches.find(branch => branch.name === source.label);
    return { source: source.label, remote: remote.label, target: target.trim(), setUpstream: known?.upstream !== `${remote.label}/${target.trim()}` };
  }

  private async inspectPush(root: string, source: string, remote: string, target: string): Promise<PushPreview> {
    const remoteRef = `${remote}/${target}`;
    const result = await runProcess("git", ["rev-list", "--left-right", "--count", `${remoteRef}...${source}`], root, 30_000);
    this.log(result);
    const [behindText = "0", aheadText = "0"] = result.stdout.trim().split(/\s+/u);
    const behind = Number(behindText) || 0, ahead = Number(aheadText) || 0;
    const canFastForward = result.exitCode === 0 ? behind === 0 : true;
    return { source, remote, target, ahead, behind, canFastForward, message: result.exitCode === 0 ? (behind ? `Destination is ${behind} commit(s) ahead. A normal push is likely to be rejected; fetch/review first.` : `${ahead} commit(s) will be sent. Normal push only; force push is never used.`) : `Destination ${remoteRef} does not exist locally yet. It may be created on push; fetch first if it already exists remotely.` };
  }

  async previewPush(): Promise<void> {
    const root = await this.needWorkspace();
    if (!root || !await this.trusted()) return;
    const target = await this.choosePushTarget();
    if (!target) return;
    const preview = await this.inspectPush(root, target.source, target.remote, target.target);
    this.state = { ...this.state, gitGraph: { ...this.state.gitGraph, push: preview } };
    this.render();
  }

  async pushBranch(): Promise<void> {
    this.lastPushOutcome = undefined;
    const root = await this.needWorkspace();
    if (!root || !await this.trusted()) { this.lastPushOutcome = "cancelled"; return; }
    const target = await this.choosePushTarget();
    if (!target) { this.lastPushOutcome = "cancelled"; return; }
    const preview = await this.inspectPush(root, target.source, target.remote, target.target);
    this.state = { ...this.state, gitGraph: { ...this.state.gitGraph, push: preview } };
    this.render();
    if (!preview.canFastForward) { this.lastPushOutcome = "error"; await vscode.window.showWarningMessage(preview.message); return; }
    const choice = await vscode.window.showWarningMessage(`Push '${target.source}' to '${target.remote}/${target.target}'?\n${preview.message}\nGit will use your existing system credentials or SSH key. No force push is available.`, { modal: true }, "Push branch");
    if (choice !== "Push branch") { this.lastPushOutcome = "cancelled"; return; }
    const result = await runProcess("git", ["push", ...buildPushArgs(target.remote, target.source, target.target, target.setUpstream)], root, 180_000);
    this.log(result);
    if (result.exitCode !== 0) { this.lastPushOutcome = "error"; await vscode.window.showErrorMessage(result.stderr.trim() || "Git push failed. Check your Git Credential Manager/SSH key and CodeSlicer Output."); }
    else { this.lastPushOutcome = "success"; await vscode.window.showInformationMessage(`Pushed ${target.source} to ${target.remote}/${target.target}.`); await this.refresh(); await this.showGitBranches(); }
  }

  async configureGitHubToken(): Promise<void> {
    const token = await vscode.window.showInputBox({ title: "GitHub access token (optional)", prompt: "Stored in VS Code Secret Storage for future GitHub API features. Push uses Git Credential Manager or SSH instead.", password: true, ignoreFocusOut: true, validateInput: value => value.trim().length >= 20 ? undefined : "Paste a GitHub token, or cancel to keep using GitHub OAuth." });
    if (token === undefined) return;
    await this.context.secrets.store("codeslicer.githubToken", token.trim());
    this.state = { ...this.state, integration: { ...this.state.integration, githubTokenConfigured: true, githubStatus: "GitHub token saved in VS Code Secret Storage. It is not added to remotes or shown in logs." } };
    this.render();
    await vscode.window.showInformationMessage("GitHub token saved securely. Push still uses your OS Git Credential Manager or SSH key.");
  }

  async installGraphify(): Promise<void> {
    this.state = { ...this.state, graphify: { status: "idle", message: "Graphify is optional and is never downloaded or installed by CodeSlicer. Configure an existing executable only if you explicitly choose to use it." } };
    this.render();
  }

  async buildGraphifyGraph(): Promise<void> {
    const root = await this.needWorkspace();
    if (!root || !await this.trusted()) return;
    const executable = this.config<string>("graphifyExecutable").trim() || "graphify";
    const output = join(root, ".codeslicer", "artifacts", "graphify");
    this.state = { ...this.state, graphify: { status: "running", message: "Building a separate local architecture graph…" } };
    this.render();
    const result = await runProcess(executable, ["extract", root, "--code-only", "--out", output], root, 300_000);
    this.log(result);
    const candidates = [join(output, "graphify-out", "graph.json"), join(output, "graph.json")];
    const graph = candidates.find(existsSync);
    if (result.exitCode !== 0 || !graph) {
      this.state = { ...this.state, graphify: { status: "error", message: result.stderr.trim() || "Graphify did not create graph.json. Install it or choose its executable in Settings." } };
      this.render();
      return;
    }
    await vscode.workspace.getConfiguration("codeslicer").update("graphifyGraphPath", graph, vscode.ConfigurationTarget.Workspace);
    this.state = { ...this.state, project: { ...this.state.project, graphifyAvailable: true, graphifyPath: graph }, graphify: { status: "ready", graphPath: graph, message: "Graphify architecture graph is ready. It remains separate from CodeSlicer risk and evidence." } };
    this.render();
  }

  private async executable(root: string): Promise<string | undefined> {
    const runtime = await this.runtime.validate(root, this.config<string>("executable"));
    this.state = { ...this.state, runtime };
    this.render();
    if (runtime.status === "found" && runtime.executable) return runtime.executable;
    await vscode.window.showErrorMessage(`CodeSlicer runtime unavailable: ${runtime.diagnostic}`);
    return undefined;
  }

  private async base(root: string): Promise<string | undefined> {
    const configured = this.config<string>("baseRef").trim();
    const selection = await detectBaseSelection(root, configured);
    const value = configured || selection.base || (selection.candidates.length ? await vscode.window.showQuickPick(selection.candidates, { title: "Choose the base branch for this review", placeHolder: "CodeSlicer could not determine one base branch" }) : undefined);
    if (!value) {
      await vscode.window.showErrorMessage("No verified base branch was found. Choose a branch before reviewing changes.");
      return undefined;
    }
    if (!isSafeRef(value)) {
      await vscode.window.showErrorMessage("codeslicer.baseRef is not a safe local Git ref. Configure a branch name such as main.");
      return undefined;
    }
    const result = await runProcess("git", ["rev-parse", "--verify", "--quiet", value], root, 15_000);
    this.log(result);
    if (result.exitCode === 0) return value;
    await vscode.window.showErrorMessage(`Local base branch '${value}' was not found. Use “Configure base branch” to choose an existing local branch.`);
    return undefined;
  }

  async analyze(): Promise<void> {
    const root = await this.needWorkspace();
    if (!root || !await this.trusted()) return;
    const executable = await this.executable(root);
    if (!executable) return;
    this.setAnalysisProgress("running", 0);
    try {
      await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "CodeSlicer: analyzing workspace", cancellable: true }, async (progress, token) => {
        const controller = new AbortController();
        token.onCancellationRequested(() => controller.abort());
        let previous = 0;
        const result = await runProcess(executable, buildAnalyzeArgs(root), root, {
          timeoutMs: 1_800_000,
          signal: controller.signal,
          onStderrLine: line => parseJsonLineProgress(line).forEach(event => {
            const next = Math.max(previous, Math.min(100, event.overall_percent ?? previous));
            progress.report({ message: event.message, increment: Math.max(0, next - previous) });
            previous = next;
            this.setAnalysisProgress("running", next, event.message, {
              processed: Number.isFinite(event.processed) ? event.processed : undefined,
              total: Number.isFinite(event.total) ? event.total : undefined,
              elapsedSeconds: Number.isFinite(event.elapsed_seconds) ? event.elapsed_seconds : undefined,
              etaSeconds: typeof event.eta_seconds === "number" && Number.isFinite(event.eta_seconds) ? event.eta_seconds : undefined,
            });
          })
        });
        this.log(result);
        if (result.cancelled) throw new Error("Analysis cancelled. Existing cache and graph were left unchanged.");
        if (result.timedOut) throw new Error("Analysis timed out. CodeSlicer stopped its process tree; the next run will recover any stale analysis lock automatically.");
        if (result.exitCode !== 0) throw new Error(result.stderr || "CodeSlicer analysis failed.");
      });
      this.setAnalysisProgress("ready", 100);
      await this.refresh();
    } catch (error) {
      this.setAnalysisProgress("error", this.state.analysis.percent, String(error));
      throw error;
    }
  }

  async setReviewSource(mode: ReviewSourceMode): Promise<void> {
    if (mode === "github-pr") {
      const url = await vscode.window.showInputBox({ title: "Review a GitHub pull request", prompt: "GitHub pull-request URL. This starts OAuth and two read-only GitHub API requests only after you continue.", placeHolder: "https://github.com/owner/repository/pull/42", ignoreFocusOut: true });
      if (url === undefined) return;
      try {
        const prepared = await this.github.preparePullRequestReviewAfterUserAction(url);
        const reviewDirectory = join(this.context.globalStorageUri.fsPath, "reviews");
        await mkdir(reviewDirectory, { recursive: true });
        const key = createHash("sha256").update(url).digest("hex").slice(0, 16);
        const diffFile = join(reviewDirectory, `github-pr-${key}.diff`);
        await writeFile(diffFile, prepared.review.diff, "utf8");
        this.state = { ...this.state, reviewSource: { mode, diffFile, baseRef: prepared.review.baseRef, label: `${prepared.review.reference.owner}/${prepared.review.reference.repository}#${prepared.review.reference.number}` }, integration: { ...this.state.integration, githubAuthenticated: true, githubStatus: `Signed in as ${prepared.accountLabel}. GitHub diff downloaded locally; no code was uploaded.` } };
        await this.context.workspaceState.update("codeslicer.reviewSource", this.state.reviewSource);
        this.render();
        await vscode.window.showInformationMessage("GitHub pull-request diff is ready for local CodeSlicer review.");
      } catch (error) {
        await vscode.window.showErrorMessage(`GitHub pull-request setup failed: ${String(error)}`);
      }
      return;
    }
    let diffFile: string | undefined;
    if (mode === "diff-file") {
      const picked = await vscode.window.showOpenDialog({ title: "Choose a local diff file", canSelectMany: false, canSelectFiles: true, canSelectFolders: false, filters: { "Diff files": ["diff", "patch"] }, openLabel: "Use this diff" });
      if (!picked?.[0]) return;
      diffFile = picked[0].fsPath;
    }
    this.state = { ...this.state, reviewSource: { mode, diffFile } };
    await this.context.workspaceState.update("codeslicer.reviewSource", this.state.reviewSource);
    this.render();
  }

  async review(includePotential = false): Promise<void> {
    const root = await this.needWorkspace();
    if (!root || !await this.trusted()) return;
    const executable = await this.executable(root);
    if (!executable) return;
    const source = this.state.reviewSource;
    const base = source.mode === "github-pr" ? source.baseRef : (source.mode === "diff-file" || source.mode === "staged") ? undefined : await this.base(root);
    if (!source.diffFile && (source.mode === "diff-file" || source.mode === "github-pr")) return;
    if (source.mode === "current-changes" || source.mode === "compare") if (!base) return;
    try {
      await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "CodeSlicer: reviewing local changes", cancellable: true }, async (progress, token) => {
        const controller = new AbortController();
        token.onCancellationRequested(() => controller.abort());
        // The bundled runtime reports analysis progress, not review progress.
        // Keep this notification indeterminate rather than repeatedly reporting a
        // fictitious 0%, which otherwise survives beside a completed result.
        progress.report({ message: "Reviewing changes" });
        const result = await runProcess(executable, buildReviewArgs(root, source, base, includePotential), root, { timeoutMs: 1_800_000, signal: controller.signal });
        this.log(result);
        if (result.cancelled) throw new Error("Review cancelled. Existing cache and graph were left unchanged.");
        if (result.timedOut) throw new Error("Review timed out. CodeSlicer stopped its process tree; the next run will recover any stale analysis lock automatically.");
        if (result.exitCode !== 0) throw new Error(result.stderr || "CodeSlicer review failed.");
        const review = parseReviewJson(result.stdout);
        this.tests = review.tests;
        this.state = withReview(this.state, review);
        progress.report({ message: "Change review complete", increment: 100 });
        await this.context.workspaceState.update("codeslicer.lastReview", review);
        const entry: ReviewHistoryEntry = { createdAt: new Date().toISOString(), source: source.mode, risk: review.riskLevel, affected: review.impacts.length };
        const history = [entry, ...this.state.history].slice(0, 10);
        this.state = { ...this.state, history };
        await this.context.workspaceState.update("codeslicer.reviewHistory", history);
      });
      this.render();
      this.showReviewReport();
      vscode.window.setStatusBarMessage("CodeSlicer: Change review complete", 5_000);
      // Keep the detailed side-panel result reachable for guides and users who
      // prefer the cockpit, but do not force the main answer into that width.
      setTimeout(() => void this.view?.webview.postMessage({ type: "openTab", tab: "results" }), 0);
    } catch (error) {
      this.state = withReview(this.state, { ...INITIAL_STATE.review, status: "error", warnings: ["Review did not complete. See the CodeSlicer Output channel for the technical log."] });
      this.render();
      // VS Code offers no public API to dismiss an old notification toast. Keep
      // technical details in Output and use an expiring status-bar message so a
      // later successful review is never visually contradicted by this failure.
      vscode.window.setStatusBarMessage("CodeSlicer: review failed — see CodeSlicer Output", 10_000);
    }
  }

  async showHistory(): Promise<void> {
    if (!this.state.history.length) {
      await vscode.window.showInformationMessage("CodeSlicer has no local review history in this workspace yet.");
      return;
    }
    await vscode.window.showQuickPick(this.state.history.map(item => ({ label: `${item.risk} risk · ${item.affected} affected`, description: `${item.source} · ${new Date(item.createdAt).toLocaleString()}` })), { title: "Local CodeSlicer review history" });
  }

  async explain(): Promise<void> {
    const root = await this.needWorkspace();
    if (!root || !await this.trusted()) return;
    const editor = vscode.window.activeTextEditor;
    const selected = editor?.document.getText(editor.selection).trim() || (editor ? editor.document.getText(editor.document.getWordRangeAtPosition(editor.selection.active) || new vscode.Range(editor.selection.active, editor.selection.active)).trim() : "");
    if (!selected) {
      await vscode.window.showInformationMessage("Place the cursor on a symbol, then run Explain selected symbol.");
      return;
    }
    const executable = await this.executable(root);
    if (!executable) return;
    const result = await runProcess(executable, ["--json", "inspect", root, "--entity", selected, "--refresh", "never"], root);
    this.log(result);
    if (result.exitCode !== 0) await vscode.window.showErrorMessage(result.stderr || "CodeSlicer could not inspect the selected entity.");
    else await vscode.window.showInformationMessage("Inspect result written to the CodeSlicer Output channel.");
  }

  async hub(graphify = false): Promise<void> {
    const url = this.localHubUrl();
    if (!url) return;
    if (graphify) url.hash = "graphify";
    await vscode.env.openExternal(vscode.Uri.parse(url.toString()));
  }

  async runTest(index?: number): Promise<"success" | "error" | "cancelled"> {
    const root = await this.needWorkspace();
    if (!root || !await this.trusted()) return "cancelled";
    const recommendation = index === undefined ? this.tests[0] : this.tests[index];
    const command = safeTestCommand(recommendation?.argv || recommendation?.command);
    if (!recommendation || !command) {
      await vscode.window.showWarningMessage("CodeSlicer did not provide a safe argv test command for this recommendation. No test was run.");
      return "error";
    }
    const choice = await vscode.window.showWarningMessage(`Run recommended test?\n${formatCommand(command)}`, { modal: true }, "Run test");
    if (choice !== "Run test") return "cancelled";
    const result = await runProcess(command[0], command.slice(1), root, 900_000);
    this.log(result);
    if (result.exitCode === 0) { await vscode.window.showInformationMessage("Recommended test passed."); return "success"; }
    await vscode.window.showErrorMessage("Recommended test failed; see CodeSlicer Output.");
    return "error";
  }

  private async setLanguage(language: unknown): Promise<void> {
    if (language !== "ru" && language !== "en") return;
    // Render immediately from the user's selection. This avoids waiting for the
    // configuration service to propagate before the webview is rebuilt.
    this.selectedLanguage = language;
    this.render();
    try {
      await vscode.workspace.getConfiguration("codeslicer").update("uiLanguage", language, vscode.ConfigurationTarget.Global);
    } catch (error) {
      OUTPUT.appendLine(`Could not save the CodeSlicer interface language: ${String(error)}`);
      await vscode.window.showWarningMessage("CodeSlicer changed language for this session, but VS Code could not save that preference.");
    }
  }

  private guideSnapshot(): { branch?: string; remotes: number; reviewStatus: string; gitStatus: string; graphStatus: string; githubToken: boolean; source: string } {
    return { branch: this.state.project.branch, remotes: this.state.gitGraph.remotes.length, reviewStatus: this.state.review.status, gitStatus: this.state.gitGraph.status, graphStatus: this.state.codeGraph.status, githubToken: this.state.integration.githubTokenConfigured, source: this.state.reviewSource.mode };
  }

  private postGuideOutcome(action: string, before: ReturnType<CockpitProvider["guideSnapshot"]>): void {
    let success = false;
    let message = "The action was cancelled or did not change the project. Read the VS Code prompt and try again.";
    if (action.startsWith("source")) success = true;
    else if (action === "review") { success = this.state.review.status === "ready"; if (this.state.review.status === "error") message = this.state.review.warnings[0] || "CodeSlicer could not review these changes. Check the Output channel and try again."; }
    else if (action === "showGit") { success = this.state.gitGraph.status === "ready"; if (this.state.gitGraph.status === "error") message = this.state.gitGraph.message; }
    else if (action === "showGraph") { success = this.state.codeGraph.status === "ready"; if (this.state.codeGraph.status === "error") message = this.state.codeGraph.message; }
    else if (action === "createBranch" || action === "switchBranch") success = Boolean(this.state.project.branch && this.state.project.branch !== before.branch);
    else if (action === "addRemote") success = this.state.gitGraph.remotes.length > before.remotes;
    else if (action === "configureGitHubToken") success = this.state.integration.githubTokenConfigured;
    else if (action === "initGit") success = this.state.project.gitStatus === "ready";
    else if (action === "configureGraphify") success = this.state.graphify.status === "ready" || this.state.project.graphifyAvailable;
    else if (action === "pushBranch") {
      success = this.lastPushOutcome === "success";
      if (this.lastPushOutcome === "cancelled") message = "The branch was not pushed. Choose a source, remote, destination branch, then confirm the push when you are ready.";
      if (this.lastPushOutcome === "error") message = "Git rejected the push. Read CodeSlicer Output, resolve the reported Git or credential problem, then try again.";
    }
    this.view?.webview.postMessage({ type: "guideEvent", action, status: success ? "success" : "error", message });
  }

  private async onMessage(message: { type: string; action?: string; entity?: string; file?: string; line?: number; index?: number; language?: unknown; guide?: { id?: unknown; step?: unknown; expected?: unknown } }): Promise<void> {
    if (message.type === "setLanguage") return this.setLanguage(message.language);
    if (message.type === "action") {
      const guided = Boolean(message.guide && typeof message.guide === "object");
      const before = guided ? this.guideSnapshot() : undefined;
      const actions: Record<string, () => Promise<void>> = {
        configure: () => this.configure(), configureBase: () => this.configureBaseRef(), refresh: () => this.refresh(), doctor: () => this.doctor(), runtimeAvailability: () => this.runtimeAvailability(), focusCockpit: async () => { await vscode.commands.executeCommand("codeslicer.cockpit.focus"); this.view?.webview.postMessage({ type: "openTab", tab: "results" }); },
        analyze: () => this.analyze(), review: () => this.review(), showPotential: () => this.review(true), explain: () => this.explain(),
        sourceCurrent: () => this.setReviewSource("current-changes"), sourceStaged: () => this.setReviewSource("staged"), sourceCompare: () => this.setReviewSource("compare"), sourceDiff: () => this.setReviewSource("diff-file"), sourceGitHub: () => this.setReviewSource("github-pr"),
        hub: () => this.hub(), graphify: () => this.hub(true), configureGraphify: () => this.configureGraphify(), installRuntime: () => this.downloadCodeSlicer(), setupSkills: () => this.setupSkills(), openProject: () => this.openOrCreateProject(), importGit: () => this.importFromGit(), initGit: () => this.initializeGit(), showDemo: () => this.showDemo(), startServer: () => this.startLocalServer(), stopServer: () => this.stopLocalServer(), showGraph: () => this.analyzeAndShowGraph(), showGit: () => this.showGitBranches(), createBranch: () => this.createBranch(), switchBranch: () => this.switchBranch(), addRemote: () => this.addRemote(), previewPush: () => this.previewPush(), pushBranch: () => this.pushBranch(), configureGitHubToken: () => this.configureGitHubToken(), installGraphify: () => this.installGraphify(), buildGraphify: () => this.buildGraphifyGraph()
      };
      try {
        await actions[message.action || ""]?.();
        if (guided && before) this.postGuideOutcome(message.action || "", before);
      } catch (error) {
        if (guided) this.view?.webview.postMessage({ type: "guideEvent", action: message.action || "", status: "error", message: String(error) });
        else throw error;
      }
      return;
    }
    if (message.type === "runTest") {
      const outcome = await this.runTest(message.index);
      if (message.guide) this.view?.webview.postMessage({ type: "guideEvent", action: "runTest", status: outcome === "success" ? "success" : "error", message: outcome === "cancelled" ? "The test was not started. Confirm the command when you are ready." : "The test failed. Open CodeSlicer Output, correct the problem, then try again." });
      return;
    }
    if (message.type === "chain") {
      const chain = this.state.review.chains[message.index || 0];
      this.view?.webview.postMessage({ type: "details", text: chain ? `${chain.nodeIds.join(" → ")}\n${chain.evidence.map(evidence => `${evidence.file || "unknown"}:${evidence.line || "?"} ${evidence.text || ""}`).join(" · ")}` : "No evidence chain." });
      return;
    }
    if (message.type === "entity") {
      const impact = this.state.review.impacts.find(item => item.entityId === message.entity);
      const details = impact ? `${impact.label}: ${impact.reason}\n${impact.evidence.map(evidence => `${evidence.file || impact.file || "unknown"}:${evidence.line || impact.line || "?"} ${evidence.text || ""} ${evidence.provenance ? `[${evidence.provenance}]` : ""}`).join(" · ")}` : message.entity || "";
      this.view?.webview.postMessage({ type: "details", text: details });
      if (message.file) try {
        const document = await vscode.workspace.openTextDocument(vscode.Uri.file(join(this.workspace() || "", message.file)));
        await vscode.window.showTextDocument(document, { selection: message.line ? new vscode.Range(message.line - 1, 0, message.line - 1, 0) : undefined, preview: true });
      } catch { /* Evidence remains visible in the map. */ }
    }
  }
}

export function activate(context: vscode.ExtensionContext): void {
  const provider = new CockpitProvider(context);
  context.subscriptions.push(vscode.window.registerWebviewViewProvider("codeslicer.cockpit", provider));
  if (vscode.workspace.getConfiguration("codeslicer").get<boolean>("codeLens")) {
    context.subscriptions.push(vscode.languages.registerCodeLensProvider({ scheme: "file" }, {
      provideCodeLenses(document): vscode.CodeLens[] {
        const first = document.lineAt(0).range;
        return [new vscode.CodeLens(first, { title: "CodeSlicer: Review current changes", command: "codeslicer.reviewCurrentChanges" })];
      }
    }));
  }
  for (const [id, handler] of [
    ["codeslicer.configureExecutable", () => provider.configure()], ["codeslicer.installRuntime", () => provider.downloadCodeSlicer()], ["codeslicer.setupSkills", () => provider.setupSkills()], ["codeslicer.analyzeWorkspace", () => provider.analyze()], ["codeslicer.runtimeDoctor", () => provider.doctor()], ["codeslicer.runtimeUpdate", () => provider.runtimeAvailability()], ["codeslicer.runtimeRollback", () => provider.runtimeAvailability()],
    ["codeslicer.reviewCurrentChanges", () => provider.review()], ["codeslicer.reviewStagedChanges", async () => { await provider.setReviewSource("staged"); await provider.review(); }], ["codeslicer.reviewCompare", async () => { await provider.setReviewSource("compare"); await provider.review(); }], ["codeslicer.reviewDiffFile", async () => { await provider.setReviewSource("diff-file"); await provider.review(); }], ["codeslicer.githubSignIn", () => provider.setReviewSource("github-pr")], ["codeslicer.showReviewHistory", () => provider.showHistory()], ["codeslicer.explainSelectedSymbol", () => provider.explain()],
    ["codeslicer.openLocalHub", () => provider.hub()], ["codeslicer.startLocalServer", () => provider.startLocalServer()], ["codeslicer.refresh", () => provider.refresh()],
    ["codeslicer.runRecommendedTest", async () => { await provider.runTest(); }], ["codeslicer.gitCreateBranch", () => provider.createBranch()], ["codeslicer.gitSwitchBranch", () => provider.switchBranch()], ["codeslicer.gitPreviewPush", () => provider.previewPush()], ["codeslicer.gitPushBranch", () => provider.pushBranch()], ["codeslicer.configureGitHubToken", () => provider.configureGitHubToken()]
  ] as [string, () => Promise<void>][]) context.subscriptions.push(vscode.commands.registerCommand(id, handler));
}

export function deactivate(): void {
  OUTPUT.dispose();
}
