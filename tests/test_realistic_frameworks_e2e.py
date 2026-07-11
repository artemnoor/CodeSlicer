import json
import pytest
from pathlib import Path
from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.models import GraphDocument
from impact_engine.impact import impact_query

FASTAPI_REALISTIC = Path(__file__).parent / "fixtures" / "frameworks" / "fastapi_realistic"
REACT_REALISTIC = Path(__file__).parent / "fixtures" / "frameworks" / "react_realistic"
DI_REALISTIC = Path(__file__).parent / "fixtures" / "frameworks" / "dependency_injector_realistic"

def test_fastapi_realistic_e2e():
    res = analyze_project_core(str(FASTAPI_REALISTIC))
    assert res["status"] == "ok"
    graph = GraphDocument.from_json(json.dumps(res["graph"]))

    # 1. FastAPI Route node `/api/orders/` exists
    route_id = "HTTP POST /api/orders/"
    route_node = next((n for n in graph.nodes if n.id == route_id), None)
    assert route_node is not None, f"Expected route {route_id} not found"

    # 2. Route -> Route Handler endpoint
    edge_handler = next((e for e in graph.edges if e.from_node == route_id and e.to_node == "app.routers.create_order"), None)
    assert edge_handler is not None
    assert edge_handler.source == "INFERRED"
    assert edge_handler.properties.get("support_pack_id") == "fastapi"
    assert edge_handler.properties.get("resolver_hook_name") == "fastapi_router_resolver"

    # 3. Route Handler -> Depends Provider: create_order -> get_order_service
    edge_depends = next((e for e in graph.edges if e.from_node == "app.routers.create_order" and e.to_node == "app.routers.get_order_service"), None)
    assert edge_depends is not None
    assert edge_depends.source == "INFERRED"
    assert edge_depends.properties.get("support_pack_id") == "fastapi"
    assert edge_depends.properties.get("resolver_hook_name") == "fastapi_depends_resolver"

    # 4. Handler -> service method: create_order -> OrderService.create_order
    edge_service = next((e for e in graph.edges if e.from_node == "app.routers.create_order" and e.to_node == "app.services.OrderService.create_order"), None)
    assert edge_service is not None

    # 5. OrderService.create_order -> OrderRepository.save
    edge_repo = next((e for e in graph.edges if e.from_node == "app.services.OrderService.create_order" and e.to_node == "app.repositories.OrderRepository.save"), None)
    assert edge_repo is not None
    assert edge_repo.source == "INFERRED"

    # Check evidence chain
    assert len(edge_handler.evidence) >= 1
    assert edge_handler.evidence[0].file == "app/routers.py"


def test_react_realistic_e2e():
    res = analyze_project_core(str(REACT_REALISTIC))
    assert res["status"] == "ok"
    graph = GraphDocument.from_json(json.dumps(res["graph"]))

    # Since there are no ROUTE nodes in react_realistic workspace (it's pure frontend JS),
    # the frontend fetch '/api/orders/' will NOT create the fetch edge because route matching is honest!
    react_fetch_edge = next((e for e in graph.edges if e.properties.get("support_pack_id") == "react" and "http" in e.to_node.lower()), None)
    assert react_fetch_edge is None, "Should not emit fetch edge if route is unknown"

    # Now let's inject a ROUTE node 'HTTP POST /api/orders/' to simulate route matching!
    from impact_engine.models import Node
    graph.add_node(Node(id="HTTP POST /api/orders/", name="HTTP POST /api/orders/", kind="ROUTE"))

    # Re-apply react rules to see if it matches the route now!
    from impact_engine.support_packs.registry import list_local_support_packs, validate_support_pack_file
    from impact_engine.support_packs.schema import support_pack_from_dict
    react_pack_path = Path("support_packs/javascript/react/support_pack.json")
    react_pack = support_pack_from_dict(json.loads(react_pack_path.read_text(encoding="utf-8")))

    from impact_engine.support_packs.resolution import apply_support_pack_rules
    resolved = apply_support_pack_rules(graph, [react_pack])

    # 1. Component -> Hook: OrderForm -> useOrders
    edge_hook = next((e for e in resolved.edges if e.from_node == "OrderForm" and e.to_node == "useOrders"), None)
    assert edge_hook is not None
    assert edge_hook.source == "INFERRED"
    assert edge_hook.properties.get("support_pack_id") == "react"

    # 2. Hook -> API: useOrders -> postOrder
    edge_api = next((e for e in resolved.edges if e.from_node == "useOrders" and e.to_node == "postOrder"), None)
    assert edge_api is not None
    assert edge_api.source == "INFERRED"
    assert edge_api.confidence == 0.60

    # 3. API -> route endpoint: postOrder -> HTTP POST /api/orders/
    edge_fetch = next((e for e in resolved.edges if e.from_node == "postOrder" and e.to_node == "HTTP POST /api/orders/"), None)
    assert edge_fetch is not None
    assert edge_fetch.source == "INFERRED"
    assert edge_fetch.properties.get("support_pack_id") == "react"
    assert len(edge_fetch.evidence) >= 1


def test_dependency_injector_realistic_e2e():
    res = analyze_project_core(str(DI_REALISTIC))
    assert res["status"] == "ok"
    graph = GraphDocument.from_json(json.dumps(res["graph"]))

    # 1. Container binding: Container.order_service -> OrderService
    edge_binding = next((e for e in graph.edges if e.from_node == "app.container.Container.order_service" and e.to_node == "app.services.OrderService"), None)
    assert edge_binding is not None
    assert edge_binding.source == "INFERRED"
    assert edge_binding.properties.get("support_pack_id") == "dependency_injector"

    # 2. Inferred constructor dependency: OrderService -> OrderRepository
    edge_dep = next((e for e in graph.edges if e.from_node == "app.services.OrderService" and e.to_node == "app.repositories.OrderRepository"), None)
    assert edge_dep is not None
    assert edge_dep.source == "INFERRED"
    assert edge_dep.properties.get("support_pack_id") == "dependency_injector"
    assert len(edge_dep.evidence) >= 1


def test_scoping_and_evidence_regressions():
    # 1. Python graphs must not receive React edges or nodes
    res_fa = analyze_project_core(str(FASTAPI_REALISTIC))
    assert res_fa["status"] == "ok"
    graph_fa = GraphDocument.from_json(json.dumps(res_fa["graph"]))
    for edge in graph_fa.edges:
        assert edge.to_node != "react"
        assert edge.properties.get("support_pack_id") != "react"
        assert edge.properties.get("support_pack_library") != "react"

    res_di = analyze_project_core(str(DI_REALISTIC))
    assert res_di["status"] == "ok"
    graph_di = GraphDocument.from_json(json.dumps(res_di["graph"]))
    for edge in graph_di.edges:
        assert edge.to_node != "react"
        assert edge.properties.get("support_pack_id") != "react"
        assert edge.properties.get("support_pack_library") != "react"

    # 2. dependency-injector inferred edges must have non-empty file/line evidence
    di_edges = [e for e in graph_di.edges if e.properties.get("support_pack_id") == "dependency_injector" and e.source == "INFERRED"]
    assert len(di_edges) >= 2
    for edge in di_edges:
        assert edge.evidence, f"Edge {edge.id} has no evidence"
        for ev in edge.evidence:
            assert ev.file is not None, f"Edge {edge.id} has None file in evidence"
            assert ev.file != "", f"Edge {edge.id} has empty file in evidence"
            assert ev.line is not None, f"Edge {edge.id} has None line in evidence"
            assert isinstance(ev.line, int), f"Edge {edge.id} line is not an integer"
