from __future__ import annotations

from pathlib import Path
import shutil

from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.impact import impact_query
from impact_engine.models import GraphDocument
from impact_engine.review import build_review_report


FIXTURE = Path(__file__).parent / "fixtures" / "next_react_fastapi_fullstack"


def _fresh_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "fullstack"
    shutil.copytree(FIXTURE, target, ignore=shutil.ignore_patterns(".impact_engine", "__pycache__"))
    return target


def test_next_react_fastapi_endpoint_change_reaches_client_hook_component_and_test(tmp_path):
    # A repository fixture may retain a graph from an earlier test run.  This
    # regression must prove the cold pipeline itself creates the bridge.
    result = analyze_project_core(str(_fresh_fixture(tmp_path)))
    graph = GraphDocument.from_dict(result["graph"])

    assert result["diagnostics"]["frontend_backend_endpoint_bridge_status"] == "applied"

    client = "api.orders.createOrder"
    hook = "hooks.useOrders.useOrders"
    component = "components.OrderCreateForm.OrderCreateForm"
    test = "__tests__.orderFlow.test.testOrderCreateFlow"
    route = "HTTP POST /api/v1/shop/orders"
    handler = "backend.app.api.shop.create_order"

    assert any(edge.kind == "HTTP_CALLS" and edge.from_node == client and edge.to_node == route for edge in graph.edges)
    assert any(edge.kind == "MATCHES_ENDPOINT" and edge.from_node == route and edge.to_node == handler for edge in graph.edges)
    assert any(edge.kind == "DEPENDS_ON" and edge.from_node == hook and edge.to_node == client for edge in graph.edges)
    assert any(edge.kind == "DEPENDS_ON" and edge.from_node == component and edge.to_node == hook for edge in graph.edges)
    assert any(edge.kind == "TESTS" and edge.from_node == test and edge.to_node == component for edge in graph.edges)

    impact = impact_query(graph, target=handler, direction="upstream", min_confidence=0.70)
    affected = {node["id"] for node in impact["affected_nodes"]}
    affected_edges = {(edge["from"], edge["to"], edge["kind"]) for edge in impact["affected_edges"]}

    assert client in affected
    assert hook in affected
    assert component in affected
    assert test in affected
    assert (route, handler, "MATCHES_ENDPOINT") in affected_edges
    assert (client, route, "HTTP_CALLS") in affected_edges
    assert (hook, client, "DEPENDS_ON") in affected_edges
    assert (component, hook, "DEPENDS_ON") in affected_edges
    assert (test, component, "TESTS") in affected_edges


def test_js_ts_capability_diagnostics_stay_honest_for_fullstack_fixture(tmp_path):
    result = analyze_project_core(str(_fresh_fixture(tmp_path)))
    capabilities = result["diagnostics"]["language_semantic_capabilities"]

    assert capabilities["python"]["capabilities"]["production_semantic_baseline"] is True
    assert capabilities["typescript"]["capabilities"]["production_semantic_baseline"] is False
    assert capabilities["typescript"]["capabilities"]["endpoint_resolution"] is True
    assert capabilities["typescript"]["capabilities"]["call_resolution"] == "semantic"


def test_typescript_local_import_edges_are_exact_and_not_name_only(tmp_path):
    graph = GraphDocument.from_dict(analyze_project_core(str(_fresh_fixture(tmp_path)))["graph"])
    assert any(
        edge.from_node == "useOrders"
        and edge.to_node == "createOrder"
        and edge.properties.get("resolution_status") == "resolved_exact"
        and edge.properties.get("evidence_class") == "explicit_local_import"
        for edge in graph.edges
    ), [(edge.from_node, edge.to_node) for edge in graph.edges if edge.properties.get("provider") == "typescript_local_import_resolver"]


def test_limited_typescript_review_keeps_unknown_risk_but_returns_source_backed_advisory_test(tmp_path):
    root = _fresh_fixture(tmp_path)
    graph = GraphDocument.from_dict(analyze_project_core(str(root))["graph"])
    diff_text = """diff --git a/frontend/src/api/orders.ts b/frontend/src/api/orders.ts
--- a/frontend/src/api/orders.ts
+++ b/frontend/src/api/orders.ts
@@ -5,0 +6 @@ export function createOrder(payload: unknown) {
+  // changed request handling
"""

    report = build_review_report(
        str(root), graph=graph, diff_text=diff_text, diff_source="fixture",
        refresh="never", run_tests="suggested",
    )

    assert report["risk"]["level"] == "UNKNOWN"
    assert report["chains"] == []
    assert report["test_recommendations"]
    recommendation = report["test_recommendations"][0]
    assert recommendation["advisory"] is True
    assert recommendation["file"] == "frontend/src/__tests__/orderFlow.test.tsx"
    assert recommendation["evidence_ids"]
    assert report["test_plan"][0]["safety"] == "advisory_not_runnable_without_manual_command"
