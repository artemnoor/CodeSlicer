import * as vscode from "vscode";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { buildAnalyzeArgs, buildReviewArgs, formatCommand, runProcess, safeTestCommand } from "./cli";
import { parseReviewJson, withReview } from "./review";
import { isSafeRef } from "./runtime";
import { CodeSlicerRuntimeManager } from "./runtime-manager";
import { detectBaseSelection } from "./base";
import { parseJsonLineProgress } from "./progress";
import { CockpitState, INITIAL_STATE, ProjectState, ReviewState, TestRecommendation, UiLanguage } from "./types";
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
    if (saved) this.state = { ...this.state, review: saved };
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
      integration: { githubTokenConfigured: false }
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

  openDownloads(): void {
    showInstallGuide(this.language(), () => this.configure());
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

  async review(): Promise<void> {
    const root = await this.needWorkspace();
    if (!root || !await this.trusted()) return;
    const executable = await this.executable(root);
    const base = await this.base(root);
    if (!executable || !base) return;
    try {
      await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "CodeSlicer: reviewing local changes", cancellable: true }, async (_progress, token) => {
        const controller = new AbortController();
        token.onCancellationRequested(() => controller.abort());
        const result = await runProcess(executable, buildReviewArgs(root, base), root, { timeoutMs: 900_000, signal: controller.signal });
        this.log(result);
        if (result.cancelled) throw new Error("Review cancelled. Existing cache and graph were left unchanged.");
        if (result.exitCode !== 0) throw new Error(result.stderr || "CodeSlicer review failed.");
        const review = parseReviewJson(result.stdout);
        this.tests = review.tests;
        this.state = withReview(this.state, review);
        await this.context.workspaceState.update("codeslicer.lastReview", review);
      });
      this.render();
    } catch (error) {
      this.state = withReview(this.state, { ...INITIAL_STATE.review, status: "error", warnings: [String(error)] });
      this.render();
      await vscode.window.showErrorMessage(`CodeSlicer review failed: ${String(error)}`);
    }
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
        configure: () => this.configure(), configureBase: () => this.configureBaseRef(), refresh: () => this.refresh(),
        analyze: () => this.analyze(), review: () => this.review(), explain: () => this.explain(),
        hub: () => this.hub(), graphify: () => this.hub(true), configureGraphify: () => this.configureGraphify(), downloadTools: async () => this.openDownloads()
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
    ["codeslicer.configureExecutable", () => provider.configure()], ["codeslicer.downloadTools", () => provider.openDownloads()], ["codeslicer.analyzeWorkspace", () => provider.analyze()],
    ["codeslicer.reviewCurrentChanges", () => provider.review()], ["codeslicer.explainSelectedSymbol", () => provider.explain()],
    ["codeslicer.openLocalHub", () => provider.hub()], ["codeslicer.refresh", () => provider.refresh()],
    ["codeslicer.runRecommendedTest", () => provider.runTest()]
  ] as [string, () => Promise<void>][]) context.subscriptions.push(vscode.commands.registerCommand(id, handler));
}

export function deactivate(): void {
  OUTPUT.dispose();
}
