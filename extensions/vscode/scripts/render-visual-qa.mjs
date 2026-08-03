import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { INITIAL_STATE } from "../out/src/types.js";
import { renderCockpit } from "../out/src/webview/App.js";

const output = resolve(process.argv[2] || "artifacts/visual-qa");
mkdirSync(output, { recursive: true });

const ready = {
  ...INITIAL_STATE,
  runtime: { ...INITIAL_STATE.runtime, status: "found", version: "CodeSlicer runtime 0.5.3", diagnostic: "Ready" },
  project: { ...INITIAL_STATE.project, workspace: "C:/work/shop-api", readiness: "project", gitStatus: "ready", gitMessage: "Working tree has 4 changes.", branch: "feature/checkout", freshness: "Current" }
};
const results = {
  ...ready,
  review: {
    ...ready.review,
    status: "ready",
    riskLevel: "MEDIUM",
    riskConfidence: "high",
    riskReasons: ["The checkout API changed.", "The route reaches the payment service."],
    impacts: [{ entityId: "checkout", label: "Checkout API", kind: "ROUTE", confidence: "high", tier: "confirmed", file: "app/routes/checkout.py", line: 28, reason: "The changed route calls the payment service.", evidence: [{ file: "app/routes/checkout.py", line: 28, text: "router.post('/checkout')", provenance: "FastAPI route" }] }],
    tests: [{ file: "tests/test_checkout.py", symbol: "test_checkout", category: "route", confidence: "high", reason: "This test covers the changed checkout route.", argv: ["py", "-3", "-m", "pytest", "tests/test_checkout.py"] }]
  }
};
const analyzing = {
  ...ready,
  analysis: { status: "running", percent: 42, message: "Extracting relationships" }
};
const undetermined = {
  ...ready,
  review: {
    ...ready.review,
    status: "ready",
    riskLevel: "UNKNOWN",
    riskConfidence: "low",
    riskReasons: ["The analyzer could not prove the full cross-file closure."],
    impacts: [],
    tests: []
  }
};

function page(state, afterLoad = "") {
  return renderCockpit(state, "ru").replace("</body>", `<script>window.addEventListener('load',()=>{${afterLoad}});</script></body>`);
}

writeFileSync(resolve(output, "start.html"), page(ready), "utf8");
writeFileSync(resolve(output, "results.html"), page(results, "document.querySelector('[data-tab=results]').click();"), "utf8");
writeFileSync(resolve(output, "guide.html"), page(ready, "document.querySelector('[data-demo-start]').click();"), "utf8");
writeFileSync(resolve(output, "analysis-progress.html"), page(analyzing), "utf8");
writeFileSync(resolve(output, "undetermined.html"), page(undetermined, "document.querySelector('[data-tab=results]').click();"), "utf8");
