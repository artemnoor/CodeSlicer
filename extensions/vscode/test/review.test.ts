import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { parseReviewJson } from "../src/review";
import { INITIAL_STATE } from "../src/types";
import { renderCockpit } from "../src/webview";
import { clientRouter } from "../src/webview/router";

const payload = JSON.stringify({ status: "ok", risk: { level: "HIGH", confidence: "high", reasons: ["route crosses service boundary"] }, top_impacts: [{ entity_id: "app/service.py:create_order", label: "create_order", kind: "FUNCTION", confidence: "high", file: "app/service.py", line: 3, why: { evidence_locations: [{ file: "app/service.py", line: 3, text: "service calls repository", provenance: "python_ast" }] } }], chains: [], test_recommendations: [], review_projection: { tests: [{ file: "tests/test_orders.py", symbol: "tests/test_orders.py:test_create_order", category: "symbol_call", confidence: "high", reason: "test covers service", command: ["py", "-3", "-m", "pytest", "tests/test_orders.py"] }] }, warnings: [], coverage: [] });

test("parses compatible ReviewReport fields and uses projection tests without executing them", () => {
  const review = parseReviewJson(payload);
  assert.equal(review.riskLevel, "HIGH");
  assert.equal(review.impacts[0].evidence[0].provenance, "python_ast");
  assert.equal(review.tests[0].file, "tests/test_orders.py");
});

test("cockpit separates review, results, tests, technologies, history, architecture, and Git", () => {
  const html = renderCockpit({ ...INITIAL_STATE, runtime: { ...INITIAL_STATE.runtime, status: "found" }, codeGraph: { status: "ready", nodes: [{ id: "a", label: "entry", kind: "FUNCTION" }], edges: [], totalNodes: 1, totalEdges: 0, message: "Ready" }, gitGraph: { status: "ready", commits: [{ id: "123456789", parents: [], refs: "HEAD -> main", subject: "Initial" }], branches: [{ name: "main", current: true, upstream: "origin/main", tracking: "ahead 1" }], remotes: [], message: "Ready" } }, "ru");
  assert.match(html, /Проверяйте изменения до commit и merge/);
  assert.match(html, /class="app-shell"/);
  assert.match(html, /--cs-bg: #0a0a0b/);
  assert.match(html, /--cs-green: #f4f4f5/);
  assert.match(html, /#675de1/);
  assert.match(html, /#ff6564/);
  assert.match(html, /font-family: var\(--vscode-font-family, Inter/);
  assert.match(html, /\.branch-tree::before/);
  assert.doesNotMatch(html, /linear-gradient/);
  assert.match(html, /class="branch-rail"/);
  assert.match(html, /\[hidden\] \{ display: none !important; \}/);
  assert.match(html, /class="rail-nav"/);
  assert.match(html, /data-tab="review"/);
  assert.match(html, /data-tab="results"/);
  assert.match(html, /data-tab="tests"/);
  assert.match(html, /data-tab="tech"/);
  assert.match(html, /data-tab="history"/);
  assert.match(html, /data-tab="architecture"/);
  assert.match(html, /data-tab="git"/);
  assert.match(html, /data-tab="guides"/);
  assert.match(html, /data-language="en"/);
  assert.match(html, /data-action="showGraph"/);
  assert.match(html, /data-action="review"/);
  assert.match(html, /data-action="showGit"/);
  assert.match(html, /data-action="createBranch"/);
  assert.match(html, /data-guide-anchor="git-branch"/);
  assert.match(html, /Гиды по задачам/);
  assert.match(html, /Начать работу с проектом/);
  assert.match(html, /Подключить GitHub для PR/);
  assert.match(html, /Подключить готовый Graphify/);
  assert.match(html, /class="guide-spotlight"/);
  assert.match(html, /data-action="previewPush"/);
  assert.match(html, /data-action="configureGitHubToken"/);
  assert.match(html, /data-action="configureGraphify"/);
  assert.match(html, /Дополнительные пакеты можно получать только из подписанного registry/i);
  assert.match(html, /class="graph-nodes"/);
  assert.match(html, /data-guide-handle/);
  assert.match(renderCockpit(INITIAL_STATE, "en"), /data-language="ru"/);
});

test("start screen gives safe next steps for an empty folder and a project without Git", () => {
  const empty = renderCockpit({ ...INITIAL_STATE, project: { ...INITIAL_STATE.project, readiness: "empty" } }, "ru");
  assert.match(empty, /Здесь пока нет проекта/);
  assert.match(empty, /data-action="openProject"/);
  assert.match(empty, /data-action="importGit"/);
  const noGit = renderCockpit({ ...INITIAL_STATE, project: { ...INITIAL_STATE.project, readiness: "project", gitStatus: "missing" } }, "ru");
  assert.match(noGit, /Подключите Git, когда будете готовы/);
  assert.match(noGit, /data-action="initGit"/);
});

test("router changes real screens and routes only explicit actions to VS Code", () => {
  const elements = new Map<string, any>(), messages: unknown[] = [], listeners: Record<string, (event: any) => void> = {};
  const makeElement = (): any => ({ hidden: false, dataset: {}, attributes: {}, setAttribute(name: string, value: string) { this.attributes[name] = value; }, focus() {} });
  const get = (id: string) => { if (!elements.has(id)) elements.set(id, makeElement()); return elements.get(id); };
  const tabs = ["start", "review", "results", "tests", "architecture", "git", "guides", "tech", "history", "settings"].map(tab => ({ ...makeElement(), dataset: { tab } }));
  const documentStub: any = { getElementById: get, querySelectorAll: (selector: string) => selector === "[role=tab]" ? tabs : [], querySelector: (selector: string) => { const match = selector.match(/\[data-tab="([^"]+)"\]/u); return match ? tabs.find(tab => tab.dataset.tab === match[1]) : undefined; }, addEventListener: (type: string, listener: (event: any) => void) => { listeners[type] = listener; } };
  new Function("document", "acquireVsCodeApi", clientRouter)(documentStub, () => ({ getState: () => undefined, setState() {}, postMessage: (message: unknown) => messages.push(message) }));
  const click = (dataset: Record<string, string>) => listeners.click({ target: { dataset, closest() { return this; } } });
  assert.equal(tabs[0].attributes["aria-selected"], "true");
  click({ tab: "architecture" });
  assert.equal(tabs[4].attributes["aria-selected"], "true");
  click({ action: "showGraph" });
  assert.deepEqual(messages, [{ type: "action", action: "showGraph" }]);
  click({ demoStart: "" });
  assert.equal(tabs[1].attributes["aria-selected"], "true");
  click({ demoNext: "" });
  assert.equal(tabs[1].attributes["aria-selected"], "true");
  click({ demoNext: "" });
  assert.equal(tabs[1].attributes["aria-selected"], "true");
  click({ demoNext: "" });
  assert.equal(tabs[2].attributes["aria-selected"], "true");
  click({ guide: "git" });
  assert.equal(tabs[5].attributes["aria-selected"], "true");
  click({ guide: "github" });
  assert.equal(tabs[9].attributes["aria-selected"], "true");
  click({ language: "en" });
  assert.deepEqual(messages.at(-1), { type: "setLanguage", language: "en" });
});

test("extension keeps Graphify optional and separate from the local runtime", () => {
  const source = readFileSync(join(__dirname, "../../src/extension.ts"), "utf8");
  assert.match(source, /impact-engine-local-api/);
  assert.match(source, /analyzeAndShowGraph/);
  assert.doesNotMatch(source, /pip\s+install|graphifyy/u);
  assert.match(source, /"--code-only"/);
  assert.match(source, /\["--json", "inspect"/);
});
