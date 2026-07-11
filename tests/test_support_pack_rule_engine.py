import pytest
from impact_engine.models import GraphDocument, Node, Edge
from impact_engine.support_packs.resolution import apply_support_pack_rules


def test_rule_engine_call_name_emit():
    graph = GraphDocument()
    # Add a mock CALL_EXPR node
    graph.add_node(Node(
        id="call-1",
        kind="CALL_EXPR",
        name="test_call()",
        properties={"call_name": "my_lib_func", "scope": "app.services.MyService.run"}
    ))
    
    pack = {
        "library": "my_lib",
        "edge_rules": [
            {
                "id": "rule-1",
                "match": {
                    "node_kind": "CALL_EXPR",
                    "call_name": "my_lib_func"
                },
                "emit": {
                    "to": "external.library.target",
                    "kind": "CALLS",
                    "source": "SUPPORT_PACK",
                    "confidence": 0.95,
                    "description": "Resolved by my_lib support pack rule-1"
                }
            }
        ]
    }
    
    resolved = apply_support_pack_rules(graph, [pack])
    
    edge = next((e for e in resolved.edges if e.kind == "CALLS"), None)
    assert edge is not None
    assert edge.from_node == "app.services.MyService.run"
    assert edge.to_node == "external.library.target"
    assert edge.source == "SUPPORT_PACK"
    assert edge.confidence == 0.95
    assert edge.evidence[0].description == "Resolved by my_lib support pack rule-1"


def test_rule_engine_receiver_type_and_method_name_emit():
    graph = GraphDocument()
    graph.add_node(Node(
        id="call-2",
        kind="CALL_EXPR",
        name="send()",
        properties={
            "receiver": "self.adapter",
            "receiver_type": "app.adapters.EmailAdapter",
            "method_name": "send",
            "scope": "app.services.MyService.notify"
        }
    ))
    
    pack = {
        "library": "my_adapter_lib",
        "edge_rules": [
            {
                "id": "rule-2",
                "match": {
                    "node_kind": "CALL_EXPR",
                    "receiver_type": "app.adapters.EmailAdapter",
                    "method_name": "send"
                },
                "emit": {
                    "to": "smtp.server.send",
                    "kind": "DEPENDS_ON",
                    "source": "SUPPORT_PACK",
                    "confidence": 0.85
                }
            }
        ]
    }
    
    resolved = apply_support_pack_rules(graph, [pack])
    
    edge = next((e for e in resolved.edges if e.kind == "DEPENDS_ON"), None)
    assert edge is not None
    assert edge.from_node == "app.services.MyService.notify"
    assert edge.to_node == "smtp.server.send"


def test_rule_engine_ai_proposed_rejected():
    graph = GraphDocument()
    graph.add_node(Node(
        id="call-3",
        kind="CALL_EXPR",
        name="test()",
        properties={"call_name": "ai_func", "scope": "app.run"}
    ))
    
    pack = {
        "library": "ai_lib",
        "edge_rules": [
            {
                "id": "rule-ai",
                "match": {
                    "node_kind": "CALL_EXPR",
                    "call_name": "ai_func"
                },
                "emit": {
                    "to": "ai.target",
                    "kind": "CALLS",
                    "source": "AI_PROPOSED"  # Forbidden!
                }
            }
        ]
    }
    
    resolved = apply_support_pack_rules(graph, [pack])
    assert len(resolved.edges) == 0


def test_rule_engine_duplicate_rejected():
    graph = GraphDocument()
    graph.add_node(Node(
        id="call-4",
        kind="CALL_EXPR",
        name="dup()",
        properties={"call_name": "dup_func", "scope": "app.run"}
    ))
    
    # Pre-add the edge
    edge_id = "support_pack::dup_lib::rule-dup::app.run::dup.target::CALLS"
    graph.add_edge(Edge(
        id=edge_id,
        kind="CALLS",
        from_node="app.run",
        to_node="dup.target",
        source="SUPPORT_PACK",
        confidence=0.8,
        evidence=[]
    ))
    
    pack = {
        "library": "dup_lib",
        "edge_rules": [
            {
                "id": "rule-dup",
                "match": {
                    "node_kind": "CALL_EXPR",
                    "call_name": "dup_func"
                },
                "emit": {
                    "to": "dup.target",
                    "kind": "CALLS"
                }
            }
        ]
    }
    
    resolved = apply_support_pack_rules(graph, [pack])
    # Total edges should still be 1 (duplicate not added)
    assert len(resolved.edges) == 1


def test_rule_engine_invalid_rule_does_not_crash():
    graph = GraphDocument()
    # Add a mock node
    graph.add_node(Node(
        id="call-5",
        kind="CALL_EXPR",
        name="error()",
        properties={"call_name": "err_func", "scope": "app.run"}
    ))
    
    pack = {
        "library": "broken_lib",
        "edge_rules": [
            {
                "id": "broken-rule-1",
                # match is missing emit entirely!
                "match": {
                    "node_kind": "CALL_EXPR"
                }
            },
            {
                "id": "broken-rule-2",
                "match": {
                    "node_kind": "CALL_EXPR"
                },
                # emit is missing to and kind!
                "emit": {
                    "confidence": 0.9
                }
            }
        ]
    }
    
    resolved = apply_support_pack_rules(graph, [pack])
    
    # Validation errors must be recorded in metadata
    meta_key = "support_pack_validation_errors::broken_lib"
    errors = resolved.metadata.get(meta_key)
    assert errors is not None
    assert len(errors) == 2
    assert "Missing 'emit' configuration" in errors[0]["errors"]
    assert "Emit missing 'to' field" in errors[1]["errors"]


def test_rule_engine_imported_library():
    graph = GraphDocument()
    
    # 1. Add MODULE node: module:app.main
    graph.add_node(Node(
        id="module:app.main",
        kind="MODULE",
        name="app.main",
        properties={"name": "app.main"}
    ))
    
    # 2. Add IMPORTS edge: module:app.main -> module:requests
    graph.add_edge(Edge(
        id="module:app.main__IMPORTS__module:requests",
        kind="IMPORTS",
        from_node="module:app.main",
        to_node="module:requests",
        source="EXTRACTED",
        confidence=1.0,
        evidence=[]
    ))
    
    # 3. Add CALL_EXPR node with scope = app.main.run
    graph.add_node(Node(
        id="call-requests",
        kind="CALL_EXPR",
        name="get()",
        properties={"scope": "app.main.run", "call_name": "requests.get"}
    ))
    
    # 4. Support pack rule
    pack = {
        "library": "requests_lib",
        "edge_rules": [
            {
                "id": "rule-requests",
                "match": {
                    "node_kind": "CALL_EXPR",
                    "imported_library": "requests"
                },
                "emit": {
                    "to": "external:requests",
                    "kind": "DEPENDS_ON",
                    "source": "SUPPORT_PACK",
                    "confidence": 0.81
                }
            }
        ]
    }
    
    resolved = apply_support_pack_rules(graph, [pack])
    
    # 5. Assertions
    edge = next((e for e in resolved.edges if e.kind == "DEPENDS_ON"), None)
    assert edge is not None
    assert edge.source == "SUPPORT_PACK"
    assert edge.from_node == "app.main.run"
    assert edge.to_node == "external:requests"
    assert edge.confidence == 0.81
