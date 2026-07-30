import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { parseReviewJson } from "../src/review";
import { INITIAL_STATE } from "../src/types";
import { renderCockpit } from "../src/webview";

const payload = JSON.stringify({ status: "ok", risk: { level: "HIGH", confidence: "high", reasons: ["route crosses service boundary"] }, top_impacts: [{ entity_id: "app/service.py:create_order", label: "create_order", kind: "FUNCTION", confidence: "high", file: "app/service.py", line: 3, why: { evidence_locations: [{ file: "app/service.py", line: 3, text: "service calls repository", provenance: "python_ast" }] } }], chains: [{ node_ids: ["app/service.py:create_order", "app/repo.py:save"], edge_ids: ["e1"], evidence_locations: [{ file: "app/service.py", line: 3, text: "service calls repository" }] }], test_recommendations: [], review_projection: { tests: [{ file: "tests/test_orders.py", symbol: "tests/test_orders.py:test_create_order", category: "symbol_call", confidence: "high", reason: "test covers service", command: ["py", "-3", "-m", "pytest", "tests/test_orders.py"] }] }, warnings: ["bounded review"], coverage: [{ language: "python", status: "supported" }, { language: "csharp", status: "limited" }] });

test("parses compatible ReviewReport fields and uses projection tests without executing them", () => {
  const review = parseReviewJson(payload);
  assert.equal(review.riskLevel, "HIGH");
  assert.equal(review.impacts[0].evidence[0].provenance, "python_ast");
  assert.equal(review.tests[0].file, "tests/test_orders.py");
  assert.deepEqual(review.limitations, ["csharp: limited"]);
});

test("webview offers five plain-language Russian sections and a safe first run", () => {
  const html = renderCockpit({ ...INITIAL_STATE, project: { ...INITIAL_STATE.project, branch: "feature/review", baseRef: "main" } }, "ru");
  assert.match(html, /Узнайте, что затронут ваши изменения/);
  assert.match(html, /Код остаётся на вашем компьютере/);
  assert.match(html, /Начать проверку/);
  assert.match(html, /Проверка/);
  assert.match(html, /Результат/);
  assert.match(html, /Архитектура/);
  assert.match(html, /Настройки/);
  assert.match(html, /role="tablist"/);
  assert.match(html, /data-action="configureGraphify"/);
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
});

test("download guide keeps CodeSlicer and optional Graphify explicit and separate", () => {
  const source = readFileSync(join(__dirname, "../../src/install-guide.ts"), "utf8");
  assert.match(source, /Скачать CodeSlicer/);
  assert.match(source, /Скачать Graphify/);
  assert.match(source, /data-action="downloadCodeSlicer"/);
  assert.match(source, /data-action="downloadGraphify"/);
  assert.match(source, /data-action="configureCodeSlicer"/);
  assert.match(source, /не запускается без нажатия кнопки/);
  assert.match(source, /env\.openExternal/);
});
