from impact_engine.impact import explain_edge, impact_query
from impact_engine.models import Edge, Evidence, GraphDocument, Node


def _quality_graph() -> GraphDocument:
    graph = GraphDocument()
    for node_id in ["A", "B", "C", "D"]:
        graph.add_node(Node(id=node_id, kind="FUNCTION", name=node_id))
    graph.add_edge(
        Edge(
            id="a_to_b",
            kind="CALLS",
            from_node="A",
            to_node="B",
            source="INFERRED",
            confidence=0.9,
            evidence=[Evidence(description="confirmed binding")],
        )
    )
    graph.add_edge(
        Edge(
            id="b_to_c_suspicious",
            kind="CALLS",
            from_node="B",
            to_node="C",
            source="INFERRED",
            confidence=0.95,
            evidence=[Evidence(description="suffix-only route similarity")],
            properties={"status": "suspicious", "warnings": ["prefix differs: /api/orders vs /orders"]},
        )
    )
    graph.add_edge(
        Edge(
            id="a_to_d_weak",
            kind="CALLS",
            from_node="A",
            to_node="D",
            source="EXTRACTED",
            confidence=0.6,
            evidence=[Evidence(description="static low confidence call")],
        )
    )
    return graph


def test_impact_query_excludes_suspicious_from_traversal_and_buckets_edges():
    result = impact_query(_quality_graph(), target="A", direction="downstream")

    affected = {node["id"] for node in result["affected_nodes"]}
    assert "B" in affected
    assert "D" in affected
    assert "C" not in affected

    assert any(edge["id"] == "a_to_b" for edge in result["confirmed"])
    assert any(edge["id"] == "a_to_d_weak" for edge in result["weak"])
    assert not any(edge["id"] == "b_to_c_suspicious" for edge in result["confirmed"])
    assert result["suspicious"] == []


def test_explain_edge_reports_quality_status_and_warnings():
    result = explain_edge(_quality_graph(), "B", "C", kind="CALLS")

    assert result["found"] is True
    assert result["status"] == "suspicious"
    assert result["quality"]["status"] == "suspicious"
    assert any("prefix differs" in warning for warning in result["warnings"])
