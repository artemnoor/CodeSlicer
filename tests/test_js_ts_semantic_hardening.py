from __future__ import annotations

from pathlib import Path

from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.impact import impact_query
from impact_engine.models import GraphDocument


FIXTURE = Path(__file__).parent / "fixtures" / "next_react_fastapi_fullstack"


def test_next_react_fastapi_endpoint_change_reaches_client_hook_component_and_test():
    result = analyze_project_core(str(FIXTURE))
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


def test_js_ts_capability_diagnostics_stay_honest_for_fullstack_fixture():
    result = analyze_project_core(str(FIXTURE))
    capabilities = result["diagnostics"]["language_semantic_capabilities"]

    assert capabilities["python"]["capabilities"]["production_semantic_baseline"] is True
    assert capabilities["typescript"]["capabilities"]["production_semantic_baseline"] is False
    assert capabilities["typescript"]["capabilities"]["endpoint_resolution"] is True
    assert capabilities["typescript"]["capabilities"]["call_resolution"] == "limited"
