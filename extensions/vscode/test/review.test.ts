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

test("first screen reacts to an empty folder and offers safe next steps", () => {
  const html = renderCockpit({ ...INITIAL_STATE, project: { ...INITIAL_STATE.project, readiness: "empty" } }, "ru");
  assert.match(html, /Похоже, эта папка пока пуста/);
  assert.match(html, /data-action="openProject"/);
  assert.match(html, /data-action="importGit"/);
  assert.match(html, /data-demo-start/);
  assert.match(html, /не скачивает файлы, не запускает CLI/);
});

test("ready project starts with install and review instead of empty-folder actions", () => {
  const html = renderCockpit(INITIAL_STATE, "en");
  assert.match(html, /Your project is ready for review/);
  assert.match(html, /data-action="installRuntime"/);
  assert.match(html, /data-action="review"/);
  assert.match(html, /safe simulation/);
});

test("router opens Start first, changes tabs, and forwards only explicit actions", () => {
  const elements = new Map<string, any>();
  const messages: unknown[] = [];
  const listeners: Record<string, (event: any) => void> = {};
  const makeElement = (): any => ({ hidden: false, dataset: {}, attributes: {}, setAttribute(name: string, value: string) { this.attributes[name] = value; }, focus() {} });
  const get = (id: string) => { if (!elements.has(id)) elements.set(id, makeElement()); return elements.get(id); };
  const tabs = ["start", "check", "result", "tests", "architecture", "settings"].map(tab => ({ ...makeElement(), dataset: { tab } }));
  const documentStub: any = { getElementById: get, querySelectorAll: (selector: string) => selector === "[role=tab]" ? tabs : [], querySelector: (selector: string) => tabs.find(tab => selector.includes(tab.dataset.tab)), addEventListener: (type: string, listener: (event: any) => void) => { listeners[type] = listener; } };
  new Function("document", "acquireVsCodeApi", clientRouter)(documentStub, () => ({ getState: () => undefined, setState() {}, postMessage: (message: unknown) => messages.push(message) }));
  const click = (dataset: Record<string, string>) => listeners.click({ target: { dataset, closest() { return this; } } });
  assert.equal(tabs[0].attributes["aria-selected"], "true");
  click({ tab: "check" });
  assert.equal(tabs[1].attributes["aria-selected"], "true");
  click({ action: "installRuntime" });
  assert.deepEqual(messages, [{ type: "action", action: "installRuntime" }]);
});

test("automatic install and optional IDE picker are exposed without the former guide", () => {
  const manifest = readFileSync(join(__dirname, "../../package.json"), "utf8");
  const source = readFileSync(join(__dirname, "../../src/extension.ts"), "utf8");
  assert.match(manifest, /codeslicer\.setupSkills/);
  assert.match(manifest, /codeslicer\.installRuntime/);
  assert.doesNotMatch(manifest, /codeslicer\.downloadTools/);
  assert.match(source, /agent install/);
  assert.match(source, /Expand-Archive/);
  assert.match(source, /managedInstallFolder/);
  assert.match(source, /-NoLaunch/);
  assert.doesNotMatch(source, /openDownloads/);
});

test("demo uses the actual tab router and does not post a process action", () => {
  assert.match(clientRouter, /selectTab\('check'\)/);
  assert.match(clientRouter, /typeValue\('main'\)/);
  assert.match(clientRouter, /selectTab\('result'\)/);
  assert.match(clientRouter, /selectTab\('tests'\)/);
  assert.match(clientRouter, /selectTab\('architecture'\)/);
  assert.doesNotMatch(clientRouter, /postMessage\(\{type:'action',action:'(?:startDemo|applyDemoChange|reviewDemo|testDemo)'/);
});

test("empty-folder actions delegate to VS Code instead of composing a shell command", () => {
  const source = readFileSync(join(__dirname, "../../src/extension.ts"), "utf8");
  assert.match(source, /executeCommand\("vscode\.openFolder"/);
  assert.match(source, /executeCommand\("git\.clone", repository\.trim\(\)\)/);
});
