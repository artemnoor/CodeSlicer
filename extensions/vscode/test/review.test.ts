import assert from "node:assert/strict";
import test from "node:test";
import { parseReviewJson } from "../src/review";
import { INITIAL_STATE } from "../src/types";
import { renderCockpit } from "../src/webview";

const payload = JSON.stringify({ status: "ok", risk: { level: "HIGH", confidence: "high", reasons: ["route crosses service boundary"] }, top_impacts: [{ entity_id: "app/service.py:create_order", label: "create_order", kind: "FUNCTION", confidence: "high", file: "app/service.py", line: 3, why: { evidence_locations: [{ file: "app/service.py", line: 3, text: "service calls repository", provenance: "python_ast" }] } }], chains: [{ node_ids: ["app/service.py:create_order", "app/repo.py:save"], edge_ids: ["e1"], evidence_locations: [{ file: "app/service.py", line: 3, text: "service calls repository" }] }], test_recommendations: [], review_projection: { tests: [{ file: "tests/test_orders.py", symbol: "tests/test_orders.py:test_create_order", category: "symbol_call", confidence: "high", reason: "test covers service", command: ["py", "-3", "-m", "pytest", "tests/test_orders.py"] }] }, warnings: ["bounded review"], coverage: [{ language: "python", status: "supported" }, { language: "csharp", status: "limited" }] });

test("parses real ReviewReport/v1 fields and uses projection tests without executing them", () => {
  const review = parseReviewJson(payload);
  assert.equal(review.riskLevel, "HIGH");
  assert.equal(review.impacts[0].evidence[0].provenance, "python_ast");
  assert.equal(review.tests[0].file, "tests/test_orders.py");
  assert.deepEqual(review.limitations, ["csharp: limited"]);
});

test("webview offers a guided Russian flow, tabs, and an explicit no-token message", () => {
  const html = renderCockpit({ ...INITIAL_STATE, project: { ...INITIAL_STATE.project, branch: "feature/review", baseRef: "main" } }, "ru");
  assert.match(html, /Проверьте изменения за три простых шага/);
  assert.match(html, /GitHub‑токен не нужен/);
  assert.match(html, /Текущая ветка/);
  assert.match(html, /feature\/review/);
  assert.match(html, /data-action="configureBase"/);
  assert.match(html, /role="tablist"/);
  assert.match(html, /id="language"/);
  assert.match(html, /type:'setLanguage'/);
  assert.match(html, /prefers-reduced-motion/);
  assert.match(html, /Как это работает\?/);
  assert.match(html, /Небольшая экскурсия/);
  assert.match(html, /tourSteps/);
  assert.match(html, /tour-skip/);
  assert.match(html, /tour-focus/);
});

test("webview renders English guidance and an honest empty impact state", () => {
  const html = renderCockpit(INITIAL_STATE, "en");
  assert.match(html, /Review your changes in three simple steps/);
  assert.match(html, /No GitHub token needed/);
  assert.match(html, /No report yet/);
  assert.match(html, /Graphify is not connected/);
  assert.match(html, /How it works/);
  assert.match(html, /This tour never runs anything for you/);
  assert.match(html, /Every test always asks for separate confirmation/);
});
