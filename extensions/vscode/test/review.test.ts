import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { parseReviewJson } from "../src/review";
import { INITIAL_STATE } from "../src/types";
import { renderCockpit, renderReviewReport } from "../src/webview";
import { clientRouter } from "../src/webview/router";
import { riskTone } from "../src/webview/state";

const payload = JSON.stringify({ status: "ok", risk: { level: "HIGH", confidence: "high", reasons: ["route crosses service boundary"] }, top_impacts: [{ entity_id: "app/service.py:create_order", label: "create_order", kind: "FUNCTION", confidence: "high", file: "app/service.py", line: 3, why: { evidence_locations: [{ file: "app/service.py", line: 3, text: "service calls repository", provenance: "python_ast" }] } }], chains: [], test_recommendations: [], review_projection: { tests: [{ file: "tests/test_orders.py", symbol: "tests/test_orders.py:test_create_order", category: "symbol_call", confidence: "high", reason: "test covers service", command: ["py", "-3", "-m", "pytest", "tests/test_orders.py"] }] }, warnings: [], coverage: [] });

test("parses compatible ReviewReport fields and uses projection tests without executing them", () => {
  const review = parseReviewJson(payload);
  assert.equal(review.riskLevel, "HIGH");
  assert.equal(review.impacts[0].evidence[0].provenance, "python_ast");
  assert.equal(review.tests[0].file, "tests/test_orders.py");
});

test("keeps possible impact separate from the primary review cards", () => {
  const review = parseReviewJson(JSON.stringify({ status: "ok", risk: { level: "LOW", confidence: "high", reasons: [] }, top_impacts: [{ entity_id: "service", label: "service", kind: "FUNCTION", impact_tier: "confirmed", confidence: "confirmed" }], potential_impacts: [{ entity_id: "dynamic", label: "dynamic call", kind: "CALL_EXPR", impact_tier: "possible", confidence: "low", reason: "unresolved dynamic call" }], chains: [], test_recommendations: [], warnings: [], coverage: [] }));
  assert.equal(review.impacts[0].tier, "confirmed");
  assert.equal(review.potentialImpacts[0].tier, "possible");
  assert.equal(review.potentialImpacts[0].confidence, "low");
  assert.equal(review.potentialImpacts[0].reason, "unresolved dynamic call");
});

test("marks limited-coverage test recommendations as advisory", () => {
  const advisory = parseReviewJson(JSON.stringify({ status: "ok", risk: { level: "UNKNOWN", confidence: "low", reasons: [] }, top_impacts: [], chains: [], test_recommendations: [{ file: "tests/test_orders.py", symbol: "test_create_order", category: "symbol_call", confidence: "confirmed", reason: "confirmed path", advisory: true, safety: "advisory_limited_coverage" }], warnings: [], coverage: [] }));
  assert.equal(advisory.tests[0].advisory, true);
  assert.equal(advisory.tests[0].safety, "advisory_limited_coverage");
});

test("does not present unknown risk as a safe green result", () => {
  assert.equal(riskTone("UNKNOWN"), "neutral");
  assert.equal(riskTone("LOW"), "good");
  assert.equal(riskTone("Not fully determined"), "neutral");
});

test("presents an unknown review as limited confidence instead of a misleading low risk", () => {
  const state = { ...INITIAL_STATE, project: { ...INITIAL_STATE.project, freshness: "Graph file found; freshness is verified by Review." }, review: { ...INITIAL_STATE.review, status: "ready" as const, riskLevel: "UNKNOWN", riskConfidence: "low" } };
  const cockpit = renderCockpit(state, "en");
  const report = renderReviewReport(state, "en");
  const russian = renderCockpit(state, "ru");
  assert.match(cockpit, />Not fully determined</);
  assert.doesNotMatch(cockpit, />UNKNOWN</);
  assert.match(cockpit, /Confidence: Limited/);
  assert.match(report, /Risk<\/small><strong>Not fully determined<\/strong><span>Confidence: Limited<\/span>/);
  assert.match(russian, />Не удалось определить полностью</);
  assert.match(russian, /Файл графа найден; актуальность проверяется во время проверки изменений\./);
});

test("shows a persistent accessible percentage while the project is being analyzed", () => {
  const html = renderCockpit({ ...INITIAL_STATE, analysis: { status: "running", percent: 42, message: "Extracting relationships" } }, "en");
  assert.match(html, /Project analysis/);
  assert.match(html, />42%<\/b>/);
  assert.match(html, /role="progressbar"[^>]*aria-valuenow="42"/);
  assert.match(html, /analysis-progress__track/);
});

test("cockpit separates review, results, tests, technologies, history, architecture, and Git", () => {
  const html = renderCockpit({ ...INITIAL_STATE, runtime: { ...INITIAL_STATE.runtime, status: "found" }, codeGraph: { status: "ready", nodes: [{ id: "a", label: "entry", kind: "FUNCTION" }], edges: [], totalNodes: 1, totalEdges: 0, message: "Ready" }, gitGraph: { status: "ready", commits: [{ id: "123456789", parents: [], refs: "HEAD -> main", subject: "Initial" }], branches: [{ name: "main", current: true, upstream: "origin/main", tracking: "ahead 1" }], remotes: [], message: "Ready" } }, "ru");
  assert.match(html, /Поймите, что изменится в проекте до ревью/);
  assert.match(html, /class="app-shell"/);
  assert.match(html, /--cs-bg: #0a0a0b/);
  assert.match(html, /--cs-green: #f4f4f5/);
  assert.match(html, /font-family: var\(--vscode-font-family, Inter/);
  assert.match(html, /\.branch-tree::before/);
  assert.match(html, /class="branch-rail"/);
  assert.match(html, /\[hidden\] \{ display: none !important; \}/);
  assert.match(html, /class="rail-nav"/);
  assert.match(html, />Начать</);
  assert.match(html, />Проверить изменения</);
  assert.match(html, />Карта кода</);
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
  assert.match(html, /class="readiness-card"/);
  assert.match(html, /Готовность проекта/);
  const initial = renderCockpit(INITIAL_STATE, "en");
  assert.match(initial, /data-language="ru"/);
  assert.match(initial, /Preparing runtime… Check readiness\./);
  assert.match(initial, /readiness-item is-preparing/);
  assert.match(initial, /readiness-item is-preparing"><span aria-hidden="true">…<\/span><div><strong>CodeSlicer is ready to run<\/strong>/);
  assert.match(initial, /position: sticky !important; inset-block-start: 0; z-index: 50/);
  assert.match(initial, /text-overflow: ellipsis; white-space: nowrap/);
});

test("results keep broad discovery collapsed and clearly marked", () => {
  const html = renderCockpit({ ...INITIAL_STATE, review: { ...INITIAL_STATE.review, status: "ready", impacts: [{ entityId: "confirmed", label: "save", kind: "METHOD", confidence: "confirmed", tier: "confirmed", reason: "resolved call", evidence: [] }], potentialImpacts: [{ entityId: "possible", label: "dynamic call", kind: "CALL_EXPR", confidence: "low", tier: "possible", reason: "unresolved dynamic call", evidence: [] }], rejectedRelations: [{ from: "HTTP POST /orders", to: "create_order", kind: "ROUTE_HANDLES", reason: "explicit resolver status: rejected", evidence: [] }], potentialLimitations: ["The analysis graph may not match the current project."] } }, "en");
  assert.match(html, /<details class="potential-impact-panel">/);
  assert.match(html, /Show potential scope/);
  assert.match(html, /Possible/);
  assert.match(html, /Confidence: low/);
  assert.match(html, /Why: unresolved dynamic call/);
  assert.match(html, /Unconfirmed relationships/);
  assert.match(html, /What CodeSlicer could not confirm/);
  assert.match(html, /impact-card--confirmed/);
  assert.match(html, /impact-card--possible/);
});

test("review result opens as a readable editor document without losing evidence or test controls", () => {
  const html = renderReviewReport({ ...INITIAL_STATE, project: { ...INITIAL_STATE.project, freshness: "fresh" }, review: { ...INITIAL_STATE.review, status: "ready", riskLevel: "HIGH", riskConfidence: "high", riskReasons: ["public API boundary changed"], impacts: [{ entityId: "route", label: "POST /orders", kind: "ROUTE", confidence: "confirmed", tier: "confirmed", reason: "changed handler", evidence: [{ file: "app/routes.py", line: 12, text: "route handler", provenance: "fastapi" }] }], potentialImpacts: [{ entityId: "dynamic", label: "dynamic call", kind: "CALL", confidence: "low", tier: "possible", reason: "unresolved dynamic call", evidence: [] }], tests: [{ file: "tests/test_orders.py", symbol: "test_create", category: "route", confidence: "high", reason: "covers the changed route", argv: ["py", "-3", "-m", "pytest", "tests/test_orders.py"] }] } }, "en");
  assert.match(html, /class="review-report"/);
  assert.match(html, /Change review complete/);
  assert.match(html, /Do this now/);
  assert.match(html, /What may be affected/);
  assert.match(html, /Show potential scope/);
  assert.match(html, /data-action="focusCockpit"/);
  assert.match(html, /data-test="0"/);
  assert.match(html, /data-entity="route"/);
  assert.match(html, /\.report-body \{ min-height: 100vh; overflow-x: hidden/);
  assert.match(html, /\.review-report \{ width: min\(100% - 48px, 1120px\); max-width: calc\(100% - 28px\)/);
  assert.match(html, /@media \(max-width: 680px\)/);
});

test("start screen gives safe next steps for an empty folder and a project without Git", () => {
  const empty = renderCockpit({ ...INITIAL_STATE, project: { ...INITIAL_STATE.project, readiness: "empty" } }, "ru");
  assert.match(empty, /Поймите изменения до отправки на ревью/);
  assert.match(empty, /data-action="openProject"/);
  assert.match(empty, /data-action="importGit"/);
  const noGit = renderCockpit({ ...INITIAL_STATE, project: { ...INITIAL_STATE.project, readiness: "project", gitStatus: "missing" } }, "ru");
  assert.match(noGit, /Проверим готовность проекта/);
  assert.match(noGit, /data-action="initGit"/);
});

test("router changes real screens and routes only explicit actions to VS Code", () => {
  const elements = new Map<string, any>(), messages: unknown[] = [], listeners: Record<string, (event: any) => void> = {};
  const makeElement = (): any => ({ hidden: false, dataset: {}, attributes: {}, setAttribute(name: string, value: string) { this.attributes[name] = value; }, focus() {} });
  const get = (id: string) => { if (!elements.has(id)) elements.set(id, makeElement()); return elements.get(id); };
  const tabs = ["start", "review", "results", "tests", "architecture", "git", "history", "tech", "guides", "settings"].map(tab => ({ ...makeElement(), dataset: { tab } }));
  const documentStub: any = { getElementById: get, querySelectorAll: (selector: string) => selector === "[role=tab]" ? tabs : [], querySelector: (selector: string) => { const match = selector.match(/\[data-tab="([^"]+)"\]/u); return match ? tabs.find(tab => tab.dataset.tab === match[1]) : undefined; }, addEventListener: (type: string, listener: (event: any) => void) => { listeners[type] = listener; } };
  new Function("document", "acquireVsCodeApi", "window", clientRouter)(documentStub, () => ({ getState: () => undefined, setState() {}, postMessage: (message: unknown) => messages.push(message) }), { addEventListener: (type: string, listener: (event: any) => void) => { listeners[type] = listener; } });
  const click = (dataset: Record<string, string>) => listeners.click({ target: { dataset, closest() { return this; } } });
  assert.equal(tabs[0].attributes["aria-selected"], "true");
  click({ tab: "architecture" });
  assert.equal(tabs[4].attributes["aria-selected"], "true");
  listeners.message({ data: { type: "openTab", tab: "results" } });
  assert.equal(tabs[2].attributes["aria-selected"], "true");
  click({ action: "showGraph" });
  assert.deepEqual(messages, [{ type: "action", action: "showGraph", guide: undefined }]);
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
  click({ action: "showGit" });
  assert.deepEqual(messages.at(-1), { type: "action", action: "showGit", guide: { id: "git", step: 0, expected: "showGit" } });
  click({ guide: "github" });
  assert.equal(tabs[9].attributes["aria-selected"], "true");
  listeners.keydown({ target: tabs[8], key: "ArrowRight", preventDefault() {} });
  assert.equal(tabs[9].attributes["aria-selected"], "true");
  click({ language: "en" });
  assert.deepEqual(messages.at(-1), { type: "setLanguage", language: "en" });
});

test("extension keeps Graphify optional and separate from the local runtime", () => {
  const source = readFileSync(join(__dirname, "../../src/extension.ts"), "utf8");
  assert.match(source, /"local-api"/);
  assert.match(source, /analyzeAndShowGraph/);
  assert.doesNotMatch(source, /pip\s+install|graphifyy/u);
  assert.match(source, /"--code-only"/);
  assert.match(source, /\["--json", "inspect"/);
  assert.match(source, /setAnalysisProgress/);
  assert.doesNotMatch(source, /OUTPUT\.show\(/);
});

test("interactive guides wait for the real result of a user action", () => {
  const extension = readFileSync(join(__dirname, "../../src/extension.ts"), "utf8");
  assert.match(extension, /postGuideOutcome/);
  assert.match(extension, /lastPushOutcome/);
  assert.match(extension, /type: "guideEvent"/);
  assert.match(clientRouter, /guideEvent/);
  assert.match(clientRouter, /actionMatches/);
  assert.match(clientRouter, /githubAuth/);
});
