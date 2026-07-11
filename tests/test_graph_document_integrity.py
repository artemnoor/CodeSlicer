import json
import pytest
from impact_engine.models import Edge, Evidence, GraphDocument, Node


def test_graph_document_dedupes_nodes_edges_and_evidence_with_source_priority():
    graph = GraphDocument()
    graph.add_node(Node(id="n1", kind="FUNCTION", name="fn", properties={"tags": ["a"]}))
    graph.add_node(Node(id="n1", kind="FUNCTION", name="fn", properties={"tags": ["a", "b"], "owner": "test"}))
    assert len(graph.nodes) == 1
    assert graph.nodes[0].properties["tags"] == ["a", "b"]
    assert graph.nodes[0].properties["owner"] == "test"

    graph.add_node(Node(id="n2", kind="FUNCTION", name="other"))
    ev = Evidence(description="same", file="a.py", line=1, source="test")
    graph.add_edge(Edge(
        id="e1",
        kind="CALLS",
        from_node="n1",
        to_node="n2",
        source="EXTRACTED",
        confidence=0.4,
        evidence=[ev, ev],
        properties={"rule_id": "r1"},
    ))
    graph.add_edge(Edge(
        id="e2",
        kind="CALLS",
        from_node="n1",
        to_node="n2",
        source="INFERRED",
        confidence=0.9,
        evidence=[ev, Evidence(description="new", file="a.py", line=2, source="test")],
        properties={"rule_id": "r1"},
    ))

    assert len(graph.edges) == 1
    edge = graph.edges[0]
    assert edge.source == "INFERRED"
    assert edge.confidence == 0.9
    assert len(edge.evidence) == 2

    restored = GraphDocument.from_json(graph.to_json())
    assert restored.to_dict() == graph.to_dict()
    assert json.loads(restored.to_json()) == json.loads(graph.to_json())


def test_graph_document_rejects_invalid_node_edge_source_and_confidence():
    with pytest.raises(ValueError):
        Node(id="bad", kind="NOT_A_NODE", name="bad")
    with pytest.raises(ValueError):
        Edge(id="bad", kind="NOT_EDGE", from_node="a", to_node="b")
    with pytest.raises(ValueError):
        Edge(id="bad", kind="CALLS", from_node="a", to_node="b", source="MAGIC")
    with pytest.raises(ValueError):
        Edge(id="bad", kind="CALLS", from_node="a", to_node="b", confidence=2.0)
