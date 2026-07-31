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
  const html = renderCockpit({ ...INITIAL_STATE, runtime: { ...INITIAL_STATE.runtime, status: "found" }, codeGraph: { status: "ready", nodes: [{ id: "a", label: "entry", kind: "FUNCTION" }], edges: [], totalNodes: 1, totalEdges: 0, message: "Ready" }, gitGraph: { status: "ready", commits: [{ id: "123456789", parents: [], refs: "HEAD -> main", subject: "Initial" }], branches: [], remotes: [], message: "Ready" } }, "ru");
  assert.match(html, /Проверяйте изменения до commit и merge/);
  assert.match(html, /class="app-shell"/);
  assert.match(html, /--cs-bg: #060806/);
  assert.match(html, /--cs-green: #5cf57c/);
  assert.match(html, /\[hidden\] \{ display: none !important; \}/);
  assert.match(html, /class="rail-nav"/);
  assert.match(html, /data-tab="review"/);
  assert.match(html, /data-tab="results"/);
  assert.match(html, /data-tab="tests"/);
  assert.match(html, /data-tab="tech"/);
  assert.match(html, /data-tab="history"/);
  assert.match(html, /data-tab="architecture"/);
  assert.match(html, /data-tab="git"/);
  assert.match(html, /data-language="en"/);
  assert.match(html, /data-action="showGraph"/);
  assert.match(html, /data-action="review"/);
  assert.match(html, /data-action="showGit"/);
  assert.match(html, /data-action="createBranch"/);
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
  const tabs = ["start", "review", "results", "tests", "tech", "history", "architecture", "git", "settings"].map(tab => ({ ...makeElement(), dataset: { tab } }));
  const documentStub: any = { getElementById: get, querySelectorAll: (selector: string) => selector === "[role=tab]" ? tabs : [], querySelector: (selector: string) => tabs.find(tab => selector.includes(tab.dataset.tab)), addEventListener: (type: string, listener: (event: any) => void) => { listeners[type] = listener; } };
  new Function("document", "acquireVsCodeApi", clientRouter)(documentStub, () => ({ getState: () => undefined, setState() {}, postMessage: (message: unknown) => messages.push(message) }));
  const click = (dataset: Record<string, string>) => listeners.click({ target: { dataset, closest() { return this; } } });
  assert.equal(tabs[0].attributes["aria-selected"], "true");
  click({ tab: "architecture" });
  assert.equal(tabs[6].attributes["aria-selected"], "true");
  click({ action: "showGraph" });
  assert.deepEqual(messages, [{ type: "action", action: "showGraph" }]);
  click({ demoStart: "" });
  assert.equal(tabs[1].attributes["aria-selected"], "true");
  click({ demoNext: "" });
  assert.equal(tabs[2].attributes["aria-selected"], "true");
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
