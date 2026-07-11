import pytest
import json
from impact_engine.models import GraphDocument, Node, Edge, Evidence
from impact_engine.support_packs.resolution import apply_support_pack_rules
from impact_engine.resolution.engine import resolve_graph


def test_decorator_entrypoint_rule():
    graph = GraphDocument()
    # Add a method node decorated with @app.get("/orders")
    graph.add_node(Node(
        id="app.services.OrderService.create_order",
        kind="METHOD",
        name="create_order",
        properties={
            "scope": "app.services.OrderService.create_order",
            "file": "app/services.py",
            "line": 10,
            "decorators": ["@app.get(\"/orders\")"]
        }
    ))
    
    pack = {
        "library": "fastapi",
        "version_range": ">=0.80.0",
        "language": "python",
        "edge_rules": [
            {
                "id": "fastapi-route",
                "type": "decorator_entrypoint",
                "match": {
                    "decorator": "@app.get"
                },
                "emit": {
                    "from": "HTTP GET {path}",
                    "to": "{scope}",
                    "kind": "CALLS",
                    "confidence": 0.92
                }
            }
        ]
    }
    
    # 1. Apply rules
    resolved = apply_support_pack_rules(graph, [pack])
    
    # 2. Check entrypoint node created
    assert any(n.id == "HTTP GET /orders" and n.kind == "ROUTE" for n in resolved.nodes)
    
    # 3. Check support-pack edge created
    edge = next((e for e in resolved.edges if e.kind == "CALLS"), None)
    assert edge is not None
    assert edge.from_node == "HTTP GET /orders"
    assert edge.to_node == "app.services.OrderService.create_order"
    assert edge.source == "SUPPORT_PACK"
    assert edge.confidence == 0.92
    assert edge.properties.get("support_pack_rule_id") == "fastapi-route"
    assert edge.properties.get("support_pack_library") == "fastapi"
    
    # 4. Repeated resolution does not duplicate edge
    resolved_again = apply_support_pack_rules(resolved, [pack])
    calls_edges = [e for e in resolved_again.edges if e.kind == "CALLS"]
    assert len(calls_edges) == 1


def test_constructor_injection_rule():
    graph = GraphDocument()
    graph.add_node(Node(
        id="app.services.OrderService",
        kind="CLASS",
        name="OrderService",
        properties={
            "scope": "app.services.OrderService",
            "file": "app/services.py",
            "line": 5,
            "param_type:repository": "app.repositories.OrderRepository"
        }
    ))
    
    pack = {
        "library": "dependency_injection",
        "version_range": ">=1.0.0",
        "language": "python",
        "edge_rules": [
            {
                "id": "inject-repo",
                "type": "constructor_injection",
                "match": {
                    "parameter_type": "app.repositories.OrderRepository"
                },
                "emit": {
                    "to": "app.repositories.OrderRepository",
                    "kind": "DEPENDS_ON",
                    "confidence": 0.88
                }
            }
        ]
    }
    
    resolved = apply_support_pack_rules(graph, [pack])
    edge = next((e for e in resolved.edges if e.kind == "DEPENDS_ON"), None)
    assert edge is not None
    assert edge.from_node == "app.services.OrderService"
    assert edge.to_node == "app.repositories.OrderRepository"
    assert edge.source == "SUPPORT_PACK"
    assert edge.confidence == 0.88
