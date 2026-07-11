import pytest
import json
from pathlib import Path
from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.models import GraphDocument
from impact_engine.impact import impact_query, explain_edge

FASTAPI_PROJECT = Path(__file__).parent / "fixtures" / "fastapi_realistic_project"
POLYGLOT_PROJECT = Path(__file__).parent / "fixtures" / "e2e_polyglot_project"
DI_PROJECT = Path(__file__).parent / "fixtures" / "dependency_injector_project"


def test_fastapi_e2e_pipeline():
    res = analyze_project_core(str(FASTAPI_PROJECT))
    assert res["status"] == "ok"
    
    # Load graph
    graph_dict = res["graph"]
    graph = GraphDocument.from_json(json.dumps(graph_dict))
    
    # 1. Exact node `HTTP POST /orders` exists, kind `ROUTE`
    route_node = next((n for n in graph.nodes if n.id == "HTTP POST /orders"), None)
    assert route_node is not None
    assert route_node.kind == "ROUTE"
    
    # 2. Exact edge: `HTTP POST /orders -> app.main.create_order_endpoint`
    #    kind `ROUTE_HANDLES`, source `SUPPORT_PACK`, confidence >= 0.80, support_pack_rule_id == "fastapi-post-route"
    route_edge = next((e for e in graph.edges if e.from_node == "HTTP POST /orders" and e.to_node == "app.main.create_order_endpoint"), None)
    assert route_edge is not None
    assert route_edge.kind == "ROUTE_HANDLES"
    assert route_edge.source == "SUPPORT_PACK"
    assert route_edge.confidence >= 0.80
    assert route_edge.properties.get("support_pack_rule_id") == "fastapi-post-route"
    
    # 3. Exact edge: `app.main.create_order_endpoint -> app.services.OrderService.create_order`
    #    kind `CALLS`, confidence >= 0.70, evidence non-empty
    handler_edge = next((e for e in graph.edges if e.from_node == "app.main.create_order_endpoint" and e.to_node == "app.services.OrderService.create_order"), None)
    assert handler_edge is not None
    assert handler_edge.kind == "CALLS"
    assert handler_edge.confidence >= 0.70
    assert len(handler_edge.evidence) >= 1
    
    # 4. Exact edge: `app.services.OrderService.create_order -> app.repositories.OrderRepository.save`
    #    kind `CALLS`, source `INFERRED`, confidence >= 0.80, evidence non-empty
    mvp_edge = next((e for e in graph.edges if e.from_node == "app.services.OrderService.create_order" and e.to_node == "app.repositories.OrderRepository.save"), None)
    assert mvp_edge is not None
    assert mvp_edge.kind == "CALLS"
    assert mvp_edge.source == "INFERRED"
    assert mvp_edge.confidence >= 0.80
    assert len(mvp_edge.evidence) >= 1
    
    # 5. Upstream impact query on repositories.OrderRepository.save returns:
    #    - OrderService.create_order, main.create_order_endpoint, HTTP POST /orders
    impact_res = impact_query(
        graph,
        target="app.repositories.OrderRepository.save",
        direction="upstream"
    )
    affected_ids = [n["id"] for n in impact_res["affected_nodes"]]
    assert "app.services.OrderService.create_order" in affected_ids
    assert "app.main.create_order_endpoint" in affected_ids
    assert "HTTP POST /orders" in affected_ids
    
    # 6. Minimal test edge: tests.test_orders.test_create_order -> HTTP POST /orders
    #    kind `TESTS`, source `INFERRED`, confidence >= 0.75, evidence from call expression.
    test_edge = next((e for e in graph.edges if e.from_node == "method:tests.test_orders.test_create_order" and e.to_node == "HTTP POST /orders"), None)
    assert test_edge is not None
    assert test_edge.kind == "TESTS"
    assert test_edge.source == "INFERRED"
    assert test_edge.confidence >= 0.75
    assert len(test_edge.evidence) >= 1
    assert "client.post" in test_edge.evidence[0].description


def test_polyglot_e2e_pipeline():
    res = analyze_project_core(str(POLYGLOT_PROJECT))
    assert res["status"] == "ok"
    
    graph = GraphDocument.from_json(json.dumps(res["graph"]))
    
    # Python DI/resolver edges remain high confidence (e.g. >= 0.80)
    di_edges = [e for e in graph.edges if e.source == "INFERRED" and e.kind == "CALLS"]
    assert len(di_edges) >= 1
    for de in di_edges:
        assert de.confidence >= 0.80
        
    # Weak React component/import edges exist and have lower confidence than Python DI edges (e.g., 0.40 or 0.60)
    react_edges = [e for e in graph.edges if e.properties.get("support_pack_library") == "react" and e.kind == "DEPENDS_ON"]
    assert len(react_edges) >= 1
    for re in react_edges:
        assert re.confidence < 0.80


def test_dependency_injector_e2e_pipeline():
    res = analyze_project_core(str(DI_PROJECT))
    assert res["status"] == "ok"
    
    graph = GraphDocument.from_json(json.dumps(res["graph"]))
    
    # Fixture должен создавать хотя бы один support-pack-backed edge:
    # source `SUPPORT_PACK`, confidence >= 0.80, evidence present, `support_pack_rule_id` present.
    di_edge = next((e for e in graph.edges if e.properties.get("support_pack_library") == "dependency_injector" and e.properties.get("support_pack_rule_id") == "dependency_injector_provider"), None)
    assert di_edge is not None
    assert di_edge.source == "SUPPORT_PACK"
    assert di_edge.confidence >= 0.80
    assert len(di_edge.evidence) >= 1
    assert di_edge.properties.get("support_pack_rule_id") == "dependency_injector_provider"
