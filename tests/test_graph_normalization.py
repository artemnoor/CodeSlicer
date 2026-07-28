import pytest
from impact_engine.models import GraphDocument, Node, Edge, Evidence
from impact_engine.normalization.graph import normalize_graph_document, merge_graph_documents


def test_normalize_graph_document_idempotent():
    graph = GraphDocument()
    graph.add_node(Node(id="A", kind="CLASS", name="A"))
    
    res1 = normalize_graph_document(graph)
    assert res1.metadata.get("normalized") is True
    
    # Run second time
    res2 = normalize_graph_document(res1)
    assert res2.metadata.get("normalized") is True
    assert len(res2.nodes) == 1
    assert len(res2.edges) == 0  # Creates zero new inferred edges


def test_normalize_graph_document_materializes_unresolved_dependency_endpoint():
    graph = GraphDocument()
    graph.add_node(Node(id="scope", kind="FUNCTION", name="scope"))
    graph.add_edge(Edge(id="dep", kind="DEPENDS_ON", from_node="scope", to_node="external.call"))

    normalized = normalize_graph_document(graph)
    unresolved = next(node for node in normalized.nodes if node.id == "external.call")
    assert unresolved.kind == "EXTERNAL_LIBRARY"
    assert unresolved.properties["unresolved_endpoint"] is True
    assert unresolved.properties["resolution_status"] == "unresolved"
    assert all(edge.from_node in {node.id for node in normalized.nodes} and edge.to_node in {node.id for node in normalized.nodes} for edge in normalized.edges)


def test_merge_graph_documents_deduplicates():
    g1 = GraphDocument()
    g1.add_node(Node(id="A", kind="CLASS", name="A", properties={"x": 1}))
    g1.add_edge(Edge(
        id="e1",
        kind="CALLS",
        from_node="A",
        to_node="B",
        source="EXTRACTED",
        confidence=0.8,
        evidence=[Evidence(file="file.py", line=1, description="call")]
    ))
    
    g2 = GraphDocument()
    g2.add_node(Node(id="A", kind="CLASS", name="A", properties={"y": 2}))
    g2.add_edge(Edge(
        id="e1",
        kind="CALLS",
        from_node="A",
        to_node="B",
        source="EXTRACTED",
        confidence=0.8,
        evidence=[Evidence(file="file.py", line=1, description="call")]
    ))
    
    merged = merge_graph_documents([g1, g2])
    
    # 1. Assert nodes deduplicated and properties merged
    assert len(merged.nodes) == 1
    node_A = merged.nodes[0]
    assert node_A.properties == {"x": 1, "y": 2}
    
    # 2. Assert edges deduplicated and properties preserved
    assert len(merged.edges) == 1
    edge = merged.edges[0]
    assert edge.from_node == "A"
    assert edge.to_node == "B"
    assert edge.source == "EXTRACTED"
    assert edge.confidence == 0.8
    assert len(edge.evidence) == 1
