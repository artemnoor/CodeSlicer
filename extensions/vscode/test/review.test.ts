import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { parseReviewJson } from "../src/review";
import { INITIAL_STATE } from "../src/types";
import { renderCockpit } from "../src/webview";
import { clientRouter } from "../src/webview/router";

const payload = JSON.stringify({ status: "ok", risk: { level: "HIGH", confidence: "high", reasons: ["route crosses service boundary"] }, top_impacts: [{ entity_id: "app/service.py:create_order", label: "create_order", kind: "FUNCTION", confidence: "high", file: "app/service.py", line: 3, why: { evidence_locations: [{ file: "app/service.py", line: 3, text: "service calls repository", provenance: "python_ast" }] } }], chains: [{ node_ids: ["app/service.py:create_order", "app/repo.py:save"], edge_ids: ["e1"], evidence_locations: [{ file: "app/service.py", line: 3, text: "service calls repository" }] }], test_recommendations: [], review_projection: { tests: [{ file: "tests/test_orders.py", symbol: "tests/test_orders.py:test_create_order", category: "symbol_call", confidence: "high", reason: "test covers service", command: ["py", "-3", "-m", "pytest", "tests/test_orders.py"] }] }, warnings: ["bounded review"], coverage: [{ language: "python", status: "supported" }, { language: "csharp", status: "limited" }] });

test("parses compatible ReviewReport fields and uses projection tests without executing them", () => {
  const review = parseReviewJson(payload);
  assert.equal(review.riskLevel, "HIGH");
  assert.equal(review.impacts[0].evidence[0].provenance, "python_ast");
  assert.equal(review.tests[0].file, "tests/test_orders.py");
  assert.deepEqual(review.limitations, ["csharp: limited"]);
});

test("webview offers plain-language Russian sections and a safe first run", () => {
  const html = renderCockpit({ ...INITIAL_STATE, project: { ...INITIAL_STATE.project, branch: "feature/review", baseRef: "main" } }, "ru");
  assert.match(html, /Узнайте, что затронут ваши изменения/);
  assert.match(html, /Код остаётся на вашем компьютере/);
  assert.match(html, /Начать проверку/);
  assert.match(html, /Проверка/);
  assert.match(html, /Результат/);
  assert.match(html, /Архитектура/);
  assert.match(html, /Настройки/);
  assert.match(html, /Практикум/);
  assert.match(html, /role="tablist"/);
  assert.match(html, /data-action="configureGraphify"/);
  assert.match(html, /С чего начнём/);
  assert.match(html, /Установить и настроить/);
  assert.match(html, /Подключить IDE и skills/);
  assert.match(html, /Проверить свои изменения/);
  assert.match(html, /Разобраться в архитектуре/);
  assert.match(html, /data-action="learn"/);
  assert.match(html, /data-course="pr"/);
  assert.match(html, /prefers-reduced-motion:reduce/);
});

test("webview renders English guidance and an honest empty impact state", () => {
  const html = renderCockpit({ ...INITIAL_STATE, runtime: { ...INITIAL_STATE.runtime, status: "install-unavailable" } }, "en");
  assert.match(html, /See what your changes affect/);
  assert.match(html, /Your code stays on your computer/);
  assert.match(html, /Nothing runs unless you choose an action/);
  assert.match(html, /Review GitHub Pull Request \(OAuth\)/);
  assert.match(html, /Separate architecture map/);
  assert.match(html, /data-action="sourceCompare"/);
  assert.match(html, /data-action="sourceDiff"/);
  assert.match(html, /data-action="sourceGitHub"/);
  assert.match(html, /Where should we start/);
  assert.match(html, /Install and set up/);
  assert.match(html, /Connect IDE and skills/);
  assert.match(html, /Review a GitHub PR/);
  assert.match(html, /data-course="architecture"/);
  assert.match(html, /Navigation and highlighting never start work/);
});

test("rendered webview router is valid JavaScript", () => {
  assert.doesNotThrow(() => new Function(clientRouter));
  const html = renderCockpit(INITIAL_STATE, "en");
  const script = html.match(/<script>([\s\S]*?)<\/script>/)?.[1];
  assert.ok(script, "webview should include its client router");
  assert.doesNotThrow(() => new Function(script));
});

test("learning routes navigate safely and run an action only after an explicit click", () => {
  const elements = new Map<string, any>();
  const messages: unknown[] = [];
  const listeners: Record<string, (event: any) => void> = {};
  const makeElement = (): any => ({
    hidden: false, textContent: "", dataset: {}, attributes: {}, children: [],
    classList: { add(this: any, value: string) { this.lastAdded = value; }, remove() {}, toggle(this: any, value: string, active: boolean) { this.lastToggled = [value, active]; } },
    setAttribute(name: string, value: string) { this.attributes[name] = value; },
    append(...children: any[]) { this.children.push(...children); },
    focus() {}, scrollIntoView() {}
  });
  const get = (id: string) => {
    if (!elements.has(id)) elements.set(id, makeElement());
    return elements.get(id);
  };
  const tabs = ["check", "result", "tests", "architecture", "settings", "learn"].map(tab => ({ ...makeElement(), dataset: { tab } }));
  const actionTargets = new Map<string, any>([
    ['[data-action="configureBase"]', makeElement()],
    ['[data-action="review"]', makeElement()],
    ['[data-action="hub"]', makeElement()],
    ['[data-action="configureGraphify"]', makeElement()],
    ['[data-action="downloadTools"]', makeElement()],
    ['[data-action="setupSkills"]', makeElement()],
    ['[data-action="doctor"]', makeElement()]
  ]);
  const documentStub: any = {
    documentElement: { lang: "en" },
    getElementById: get,
    createElement: makeElement,
    querySelectorAll(selector: string) { return selector === "[role=tab]" ? tabs : []; },
    querySelector(selector: string) {
      if (selector.startsWith('[data-tab=')) return tabs.find(tab => selector.includes(tab.dataset.tab));
      return actionTargets.get(selector) || get(selector.replace(/^#/, ""));
    },
    addEventListener(type: string, listener: (event: any) => void) { listeners[type] = listener; }
  };
  new Function("document", "acquireVsCodeApi", "matchMedia", clientRouter)(documentStub, () => ({ getState: () => undefined, setState() {}, postMessage: (message: unknown) => messages.push(message) }), () => ({ matches: true }));
  const click = (dataset: Record<string, string>) => listeners.click({ target: { dataset, closest() { return this; } } });

  assert.equal(tabs.find(tab => tab.dataset.tab === "learn")?.attributes["aria-selected"], "true");
  click({ course: "review" });
  assert.equal(get("course-title").textContent, "Review my changes");
  assert.deepEqual(get("panel-learn").classList.lastToggled, ["guide-active", true]);
  assert.equal(tabs.find(tab => tab.dataset.tab === "check")?.attributes["aria-selected"], "true");
  click({ learning: "show" });
  assert.equal(actionTargets.get('[data-action="configureBase"]').classList.lastAdded, "guide-focus");
  assert.deepEqual(messages, []);
  click({ learning: "perform" });
  assert.deepEqual(messages, [{ type: "action", action: "configureBase" }]);

  click({ course: "skills" });
  assert.equal(get("course-title").textContent, "Connect IDE and skills");
  assert.equal(tabs.find(tab => tab.dataset.tab === "settings")?.attributes["aria-selected"], "true");
  assert.equal(actionTargets.get('[data-action="setupSkills"]').classList.lastAdded, "guide-focus");
  click({ learning: "perform" });
  assert.deepEqual(messages, [{ type: "action", action: "configureBase" }, { type: "action", action: "setupSkills" }]);
});

test("download guide keeps CodeSlicer and optional Graphify explicit and separate", () => {
  const source = readFileSync(join(__dirname, "../../src/install-guide.ts"), "utf8");
  assert.match(source, /Скачать CodeSlicer/);
  assert.match(source, /Скачать Graphify/);
  assert.match(source, /data-action="downloadCodeSlicer"/);
  assert.match(source, /data-action="downloadGraphify"/);
  assert.match(source, /data-action="configureCodeSlicer"/);
  assert.match(source, /data-action="startWindowsSetup"/);
  assert.match(source, /data-action="setupSkills"/);
  assert.match(source, /не происходят сами/);
  assert.match(source, /env\.openExternal/);
});

test("extension exposes the IDE skills picker as an activated command", () => {
  const manifest = readFileSync(join(__dirname, "../../package.json"), "utf8");
  const source = readFileSync(join(__dirname, "../../src/extension.ts"), "utf8");
  assert.match(manifest, /codeslicer\.setupSkills/);
  assert.match(source, /agent install/);
  assert.match(source, /Open IDE picker/);
});
