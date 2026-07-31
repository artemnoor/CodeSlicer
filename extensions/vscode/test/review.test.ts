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

test("first screen gives one concise path for empty folders and ready Git projects", () => {
  const html = renderCockpit(INITIAL_STATE, "ru");
  assert.match(html, /Пустая папка или новый проект/);
  assert.match(html, /git init/);
  assert.match(html, /первый commit/);
  assert.match(html, /Есть Git-проект с изменениями/);
  assert.match(html, /data-action="installRuntime"/);
  assert.match(html, /data-action="review"/);
  assert.match(html, /IDE и skills — необязательно/);
  assert.match(html, /ИНТЕРАКТИВНОЕ ДЕМО/);
  assert.match(html, /data-action="startDemo"/);
  assert.doesNotMatch(html, /Практикум|data-course|guide-focus/);
});

test("English start screen keeps advanced paths optional", () => {
  const html = renderCockpit(INITIAL_STATE, "en");
  assert.match(html, /Empty folder or a new project/);
  assert.match(html, /initial commit/);
  assert.match(html, /A Git project with changes/);
  assert.match(html, /IDE and skills — optional/);
  assert.doesNotMatch(html, /Learning|data-course/);
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

test("interactive demo downloads only a pinned fixture and runs a predefined unittest", () => {
  const source = readFileSync(join(__dirname, "../../src/extension.ts"), "utf8");
  assert.match(source, /DEMO_COMMIT = "[a-f0-9]{40}"/);
  assert.match(source, /DEMO_ARCHIVE = `https:\/\/github\.com\/artemnoor\/CodeSlicer\/archive\/\$\{DEMO_COMMIT\}\.zip`/);
  assert.match(source, /service_di_project/);
  assert.match(source, /\["init"\], \["config", "user\.email"/);
  assert.match(source, /"unittest", "discover", "-s", "tests", "-v"/);
  assert.match(source, /projectPath/);
  assert.doesNotMatch(source, /git clone/);
});
