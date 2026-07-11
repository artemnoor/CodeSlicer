import pytest
import json
from impact_engine.models import Evidence, Node, Edge, GraphDocument, NODE_KINDS, EDGE_KINDS, EDGE_SOURCES


def test_node_validation():
    # Valid Node kinds
    for kind in NODE_KINDS:
        node = Node(id=f"node_{kind}", kind=kind, name="Test Node")
        assert node.kind == kind

    # Invalid Node kind should raise ValueError
    with pytest.raises(ValueError, match="Invalid Node kind"):
        Node(id="node_invalid", kind="INVALID_KIND", name="Bad Node")


def test_edge_validation():
    # Valid Edge kinds, sources, confidence
    for kind in EDGE_KINDS:
        for source in EDGE_SOURCES:
            edge = Edge(
                id=f"edge_{kind}",
                kind=kind,
                from_node="node_a",
                to_node="node_b",
                confidence=0.95,
                source=source
            )
            assert edge.kind == kind
            assert edge.source == source

    # Invalid Edge kind
    with pytest.raises(ValueError, match="Invalid Edge kind"):
        Edge(id="e1", kind="INVALID_KIND", from_node="a", to_node="b")

    # Invalid Edge source (provenance)
    with pytest.raises(ValueError, match="Invalid Edge source"):
        Edge(id="e2", kind="CALLS", from_node="a", to_node="b", source="INVALID_SOURCE")

    # Invalid confidence (< 0)
    with pytest.raises(ValueError, match="Invalid Edge confidence"):
        Edge(id="e3", kind="CALLS", from_node="a", to_node="b", confidence=-0.1)

    # Invalid confidence (> 1)
    with pytest.raises(ValueError, match="Invalid Edge confidence"):
        Edge(id="e4", kind="CALLS", from_node="a", to_node="b", confidence=1.1)


def test_graph_document_serialization_deserialization():
    doc = GraphDocument(metadata={"project": "test_project"})
    
    node_a = Node(id="node_a", kind="CLASS", name="OrderService")
    node_b = Node(id="node_b", kind="METHOD", name="create_order")
    doc.add_node(node_a)
    doc.add_node(node_b)

    evidence = Evidence(
        description="Direct call in code",
        file="services.py",
        line=42,
        source="extractor"
    )
    edge = Edge(
        id="edge_ab",
        kind="CONTAINS",
        from_node="node_a",
        to_node="node_b",
        confidence=1.0,
        evidence=[evidence],
        source="EXTRACTED",
        properties={"critical": True}
    )
    doc.add_edge(edge)

    # Serialize to dict
    data_dict = doc.to_dict()
    
    # Assertions for serialization contract
    serialized_edge = data_dict["edges"][0]
    assert "from" in serialized_edge
    assert "to" in serialized_edge
    assert "target" not in serialized_edge
    assert "origin" not in serialized_edge
    assert serialized_edge["from"] == "node_a"
    assert serialized_edge["to"] == "node_b"
    assert serialized_edge["source"] == "EXTRACTED"

    # Deserialize to back
    doc_from_dict = GraphDocument.from_dict(data_dict)

    assert len(doc_from_dict.nodes) == 2
    assert doc_from_dict.nodes[0].id == "node_a"
    assert doc_from_dict.nodes[0].kind == "CLASS"
    assert doc_from_dict.nodes[0].name == "OrderService"

    assert len(doc_from_dict.edges) == 1
    assert doc_from_dict.edges[0].id == "edge_ab"
    assert doc_from_dict.edges[0].kind == "CONTAINS"
    assert doc_from_dict.edges[0].from_node == "node_a"
    assert doc_from_dict.edges[0].to_node == "node_b"
    assert doc_from_dict.edges[0].confidence == 1.0
    assert doc_from_dict.edges[0].source == "EXTRACTED"
    assert doc_from_dict.edges[0].properties == {"critical": True}

    assert len(doc_from_dict.edges[0].evidence) == 1
    assert doc_from_dict.edges[0].evidence[0].description == "Direct call in code"
    assert doc_from_dict.edges[0].evidence[0].file == "services.py"
    assert doc_from_dict.edges[0].evidence[0].line == 42
    assert doc_from_dict.edges[0].evidence[0].source == "extractor"

    # Test sorting/stability of JSON
    json_str = doc.to_json()
    assert "OrderService" in json_str
    
    # Check stable sorting
    parsed_json = json.loads(json_str)
    # The JSON string should be exactly as serialized
    reconstructed_json = json.dumps(parsed_json, indent=2, sort_keys=True)
    assert json_str == reconstructed_json

    doc_from_json = GraphDocument.from_json(json_str)
    assert doc_from_json.to_dict() == doc.to_dict()


def test_inferred_edge_serialization():
    # Test that serialized edge `"source"` equals `"INFERRED"` for an inferred edge
    edge = Edge(
        id="edge-inferred",
        kind="CALLS",
        from_node="services.OrderService.create_order",
        to_node="repositories.OrderRepository.save",
        source="INFERRED",
        confidence=0.8,
        evidence=[Evidence(file="services.py", line=5, description="receiver resolved")]
    )
    doc = GraphDocument(edges=[edge])
    serialized = doc.to_dict()
    serialized_edge = serialized["edges"][0]
    
    assert serialized_edge["source"] == "INFERRED"
    assert serialized_edge["from"] == "services.OrderService.create_order"
    assert serialized_edge["to"] == "repositories.OrderRepository.save"
    assert serialized_edge["confidence"] == 0.8
    assert len(serialized_edge["evidence"]) == 1
    assert serialized_edge["evidence"][0]["file"] == "services.py"
    assert serialized_edge["evidence"][0]["line"] == 5
    assert serialized_edge["evidence"][0]["description"] == "receiver resolved"
    
    # Check that origin and target do not exist in python or serialized form
    assert not hasattr(edge, "origin")
    assert not hasattr(edge, "target")
    assert "origin" not in serialized_edge
    assert "target" not in serialized_edge
