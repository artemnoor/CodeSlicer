import * as vscode from "vscode";
import { existsSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
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
import { renderCockpit } from "./webview";
import { showInstallGuide } from "./install-guide";

const OUTPUT = vscode.window.createOutputChannel("CodeSlicer");
const graphPath = (root: string) => join(root, ".impact_engine", "graph.json");
const graphifyPath = (root: string, configured: string) => configured.trim() || join(root, ".codeslicer", "artifacts", "graphify", "graphify-out", "graph.json");

class CockpitProvider implements vscode.WebviewViewProvider {
  private view?: vscode.WebviewView;
  private state: CockpitState = structuredClone(INITIAL_STATE);
  private tests: TestRecommendation[] = [];
  private selectedLanguage?: "ru" | "en";
  private readonly runtime: CodeSlicerRuntimeManager;
  private readonly github = new GitHubReviewService();
  private readonly status: vscode.StatusBarItem;

  constructor(private readonly context: vscode.ExtensionContext) {
    this.runtime = new CodeSlicerRuntimeManager(context.globalStorageUri);
    this.status = vscode.window.createStatusBarItem("codeslicer.review", vscode.StatusBarAlignment.Left, 20);
    this.status.command = "codeslicer.reviewCurrentChanges";
    this.status.text = "$(shield) CodeSlicer: Review changes";
    this.status.tooltip = "Review current local Git changes with CodeSlicer";
    this.status.show();
    context.subscriptions.push(this.status);
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
  }

  private workspace(): string | undefined {
    return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
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

  private async projectState(root: string): Promise<ProjectState> {
    const branchResult = await runProcess("git", ["branch", "--show-current"], root, 15_000);
    this.log(branchResult);
    const branch = branchResult.exitCode === 0 ? branchResult.stdout.trim() || "detached HEAD" : "Git branch unavailable";
    const configuredGraphify = this.config<string>("graphifyGraphPath");
    const base = await detectBaseSelection(root, this.config<string>("baseRef"));
    const architectureGraph = graphifyPath(root, configuredGraphify);
    return {
      workspace: root,
      branch,
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
    OUTPUT.show(true);
  }

  async configure(): Promise<void> {
    const root = await this.needWorkspace();
    if (!root) return;
    const found = await this.runtime.discover(this.config<string>("executable"), root);
    const value = await vscode.window.showInputBox({
      title: "CodeSlicer executable",
      prompt: "Absolute path to the installed codeslicer executable",
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

  private powershellLiteral(value: string): string {
    return `'${value.replace(/'/g, "''")}'`;
  }

  private async selectCodeSlicerFolder(): Promise<string | undefined> {
    const picked = await vscode.window.showOpenDialog({
      title: "Choose the extracted CodeSlicer folder",
      canSelectMany: false,
      canSelectFiles: false,
      canSelectFolders: true,
      openLabel: "Use this CodeSlicer folder"
    });
    if (!picked?.[0]) return undefined;
    const script = join(picked[0].fsPath, "scripts", "install-windows.ps1");
    if (!existsSync(script)) {
      await vscode.window.showErrorMessage("That folder does not contain scripts/install-windows.ps1. Download and extract the official CodeSlicer archive first.");
      return undefined;
    }
    return picked[0].fsPath;
  }

  async startWindowsSetup(): Promise<void> {
    if (process.platform !== "win32") {
      await vscode.window.showInformationMessage("The guided PowerShell setup is available on Windows. Use the macOS/Linux commands in the CodeSlicer README, then choose the installed executable here.");
      return;
    }
    const folder = await this.selectCodeSlicerFolder();
    if (!folder) return;
    const choice = await vscode.window.showWarningMessage("Open PowerShell setup? It will create CodeSlicer's .venv and install CodeSlicer in the selected folder. The IDE picker appears afterwards; no IDE is selected automatically.", { modal: true }, "Open PowerShell setup");
    if (choice !== "Open PowerShell setup") return;
    const script = join(folder, "scripts", "install-windows.ps1");
    const terminal = vscode.window.createTerminal({ name: "CodeSlicer setup", cwd: folder });
    terminal.show(true);
    terminal.sendText(`powershell.exe -NoExit -ExecutionPolicy Bypass -File ${this.powershellLiteral(script)}`, true);
    await vscode.window.showInformationMessage("CodeSlicer setup opened in the integrated PowerShell terminal. Complete the visible IDE selection there, then choose codeslicer.exe in CodeSlicer settings.");
  }

  async setupSkills(): Promise<void> {
    const root = await this.needWorkspace();
    if (!root || !await this.trusted()) return;
    const executable = await this.runtime.discover(this.config<string>("executable"), root);
    if (!executable) {
      await vscode.window.showWarningMessage("Install and configure CodeSlicer first. The setup assistant can guide you there.", "Open setup assistant").then(choice => {
        if (choice === "Open setup assistant") this.openDownloads();
      });
      return;
    }
    const choice = await vscode.window.showWarningMessage("Open the IDE and skills picker in PowerShell? Choose IDEs with arrows, Space, and Enter. The installer changes only the integrations you select and creates backups before editing existing MCP files.", { modal: true }, "Open IDE picker");
    if (choice !== "Open IDE picker") return;
    const terminal = vscode.window.createTerminal({ name: "CodeSlicer IDE and skills", cwd: root });
    terminal.show(true);
    terminal.sendText(`& ${this.powershellLiteral(executable)} agent install`, true);
  }

  openDownloads(): void {
    showInstallGuide(this.language(), {
      configure: () => this.configure(),
      startWindowsSetup: () => this.startWindowsSetup(),
      setupSkills: () => this.setupSkills()
    });
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
    await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "CodeSlicer: analyzing workspace", cancellable: true }, async (progress, token) => {
      const controller = new AbortController();
      token.onCancellationRequested(() => controller.abort());
      let previous = 0;
      const result = await runProcess(executable, buildAnalyzeArgs(root), root, { timeoutMs: 900_000, signal: controller.signal, onStderrLine: line => parseJsonLineProgress(line).forEach(event => { const next = event.overall_percent || previous; progress.report({ message: event.message, increment: Math.max(0, next - previous) }); previous = next; }) });
      this.log(result);
      if (result.cancelled) throw new Error("Analysis cancelled. Existing cache and graph were left unchanged.");
      if (result.exitCode !== 0) throw new Error(result.stderr || "CodeSlicer analysis failed.");
    });
    await this.refresh();
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

  async review(): Promise<void> {
    const root = await this.needWorkspace();
    if (!root || !await this.trusted()) return;
    const executable = await this.executable(root);
    if (!executable) return;
    const source = this.state.reviewSource;
    const base = source.mode === "github-pr" ? source.baseRef : source.mode === "diff-file" ? undefined : await this.base(root);
    if (!source.diffFile && (source.mode === "diff-file" || source.mode === "github-pr")) return;
    if (source.mode === "current-changes" || source.mode === "compare") if (!base) return;
    try {
      await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "CodeSlicer: reviewing local changes", cancellable: true }, async (_progress, token) => {
        const controller = new AbortController();
        token.onCancellationRequested(() => controller.abort());
        const result = await runProcess(executable, buildReviewArgs(root, source, base), root, { timeoutMs: 900_000, signal: controller.signal });
        this.log(result);
        if (result.cancelled) throw new Error("Review cancelled. Existing cache and graph were left unchanged.");
        if (result.exitCode !== 0) throw new Error(result.stderr || "CodeSlicer review failed.");
        const review = parseReviewJson(result.stdout);
        this.tests = review.tests;
        this.state = withReview(this.state, review);
        await this.context.workspaceState.update("codeslicer.lastReview", review);
        const entry: ReviewHistoryEntry = { createdAt: new Date().toISOString(), source: source.mode, risk: review.riskLevel, affected: review.impacts.length };
        const history = [entry, ...this.state.history].slice(0, 10);
        this.state = { ...this.state, history };
        await this.context.workspaceState.update("codeslicer.reviewHistory", history);
      });
      this.render();
    } catch (error) {
      this.state = withReview(this.state, { ...INITIAL_STATE.review, status: "error", warnings: [String(error)] });
      this.render();
      await vscode.window.showErrorMessage(`CodeSlicer review failed: ${String(error)}`);
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
    const result = await runProcess(executable, ["inspect", root, "--entity", selected, "--refresh", "never", "--json"], root);
    this.log(result);
    if (result.exitCode !== 0) await vscode.window.showErrorMessage(result.stderr || "CodeSlicer could not inspect the selected entity.");
    else await vscode.window.showInformationMessage("Inspect result written to the CodeSlicer Output channel.");
  }

  async hub(graphify = false): Promise<void> {
    try {
      const url = new URL(this.config<string>("localHubUrl"));
      if (!["127.0.0.1", "localhost", "::1"].includes(url.hostname)) throw new Error();
      if (graphify) url.hash = "graphify";
      await vscode.env.openExternal(vscode.Uri.parse(url.toString()));
    } catch {
      await vscode.window.showErrorMessage("codeslicer.localHubUrl must be a loopback URL, for example http://127.0.0.1:8001/.");
    }
  }

  async runTest(index?: number): Promise<void> {
    const root = await this.needWorkspace();
    if (!root || !await this.trusted()) return;
    const recommendation = index === undefined ? this.tests[0] : this.tests[index];
    const command = safeTestCommand(recommendation?.argv || recommendation?.command);
    if (!recommendation || !command) {
      await vscode.window.showWarningMessage("CodeSlicer did not provide a safe argv test command for this recommendation. No test was run.");
      return;
    }
    const choice = await vscode.window.showWarningMessage(`Run recommended test?\n${formatCommand(command)}`, { modal: true }, "Run test");
    if (choice !== "Run test") return;
    const result = await runProcess(command[0], command.slice(1), root, 900_000);
    this.log(result);
    if (result.exitCode === 0) await vscode.window.showInformationMessage("Recommended test passed.");
    else await vscode.window.showErrorMessage("Recommended test failed; see CodeSlicer Output.");
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

  private async onMessage(message: { type: string; action?: string; entity?: string; file?: string; line?: number; index?: number; language?: unknown }): Promise<void> {
    if (message.type === "setLanguage") return this.setLanguage(message.language);
    if (message.type === "action") {
      const actions: Record<string, () => Promise<void>> = {
        configure: () => this.configure(), configureBase: () => this.configureBaseRef(), refresh: () => this.refresh(), doctor: () => this.doctor(), runtimeAvailability: () => this.runtimeAvailability(),
        analyze: () => this.analyze(), review: () => this.review(), explain: () => this.explain(),
        sourceCurrent: () => this.setReviewSource("current-changes"), sourceCompare: () => this.setReviewSource("compare"), sourceDiff: () => this.setReviewSource("diff-file"), sourceGitHub: () => this.setReviewSource("github-pr"),
        hub: () => this.hub(), graphify: () => this.hub(true), configureGraphify: () => this.configureGraphify(), downloadTools: async () => this.openDownloads(), setupSkills: () => this.setupSkills()
      };
      await actions[message.action || ""]?.();
      return;
    }
    if (message.type === "runTest") return this.runTest(message.index);
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
    ["codeslicer.configureExecutable", () => provider.configure()], ["codeslicer.downloadTools", () => provider.openDownloads()], ["codeslicer.setupSkills", () => provider.setupSkills()], ["codeslicer.analyzeWorkspace", () => provider.analyze()], ["codeslicer.runtimeDoctor", () => provider.doctor()], ["codeslicer.runtimeUpdate", () => provider.runtimeAvailability()], ["codeslicer.runtimeRollback", () => provider.runtimeAvailability()],
    ["codeslicer.reviewCurrentChanges", () => provider.review()], ["codeslicer.reviewCompare", async () => { await provider.setReviewSource("compare"); await provider.review(); }], ["codeslicer.reviewDiffFile", async () => { await provider.setReviewSource("diff-file"); await provider.review(); }], ["codeslicer.githubSignIn", () => provider.setReviewSource("github-pr")], ["codeslicer.showReviewHistory", () => provider.showHistory()], ["codeslicer.explainSelectedSymbol", () => provider.explain()],
    ["codeslicer.openLocalHub", () => provider.hub()], ["codeslicer.refresh", () => provider.refresh()],
    ["codeslicer.runRecommendedTest", () => provider.runTest()]
  ] as [string, () => Promise<void>][]) context.subscriptions.push(vscode.commands.registerCommand(id, handler));
}

export function deactivate(): void {
  OUTPUT.dispose();
}
