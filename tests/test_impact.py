import pytest
from pathlib import Path
from impact_engine.extractors.python_ast import extract_project
from impact_engine.resolution.precision import resolve_precision
from impact_engine.impact import impact_query, explain_edge
from impact_engine.models import Edge, GraphDocument, Node

PROJECT_PATH = Path(__file__).parent.parent / "examples" / "golden_cases" / "python_di_basic"


def test_impact_query_downstream_for_create_order():
    graph = extract_project(PROJECT_PATH)
    resolved = resolve_precision(graph)
    
    res = impact_query(resolved, "services.OrderService.create_order")
    
    # downstream contains repositories.OrderRepository.save
    assert "repositories.OrderRepository.save" in res["downstream"]
    
    # Assert there is a CALLS edge in edges
    calls_edge = next((e for e in res["edges"] if e["to"] == "repositories.OrderRepository.save" and e["kind"] == "CALLS"), None)
    assert calls_edge is not None
    assert calls_edge["from"] == "services.OrderService.create_order"
    assert calls_edge["source"] == "INFERRED"


def test_impact_query_upstream_for_repository_save():
    graph = extract_project(PROJECT_PATH)
    resolved = resolve_precision(graph)
    
    res = impact_query(resolved, "repositories.OrderRepository.save")
    
    # upstream contains services.OrderService.create_order
    assert "services.OrderService.create_order" in res["upstream"]
    
    # Assert there is a CALLS edge in edges
    calls_edge = next((e for e in res["edges"] if e["from"] == "services.OrderService.create_order" and e["kind"] == "CALLS"), None)
    assert calls_edge is not None
    assert calls_edge["to"] == "repositories.OrderRepository.save"
    assert calls_edge["source"] == "INFERRED"


def test_impact_query_deduplicates_edge_ids_and_preserves_bfs_result_order():
    graph = GraphDocument()
    for node_id in ("start", "left", "right", "end"):
        graph.add_node(Node(node_id, "FUNCTION", node_id))
    graph.add_edge(Edge("left-edge", "CALLS", "start", "left"))
    graph.add_edge(Edge("right-edge", "CALLS", "start", "right"))
    graph.add_edge(Edge("end-edge", "CALLS", "left", "end"))
    graph.add_edge(Edge("end-edge-2", "CALLS", "right", "end"))

    result = impact_query(graph, target="start", direction="downstream")

    assert [edge["id"] for edge in result["affected_edges"]] == [
        "left-edge", "right-edge", "end-edge", "end-edge-2"
    ]
    assert result["explanation_chain"] == [
        "start -> (CALLS, c=1.0) -> left",
        "start -> (CALLS, c=1.0) -> right",
        "start -> (CALLS, c=1.0) -> left -> (CALLS, c=1.0) -> end",
    ]
    assert result["impact_paths"][-1]["edges"] == ["left-edge", "end-edge"]


def test_impact_query_uses_constant_time_bfs_queue_and_edge_membership():
    source = Path(__file__).parents[1] / "src" / "impact_engine" / "impact.py"
    contents = source.read_text(encoding="utf-8")

    assert "from collections import deque" in contents
    assert "queue = deque()" in contents
    assert "queue.popleft()" in contents
    assert "affected_edge_ids = set()" in contents
    assert "if edge.id in affected_edge_ids:" in contents
    assert "parents: dict[str, tuple[str, Edge, str]] = {}" in contents
    assert "queue.append((next_id, depth + 1))" in contents
    assert "path_edges + [edge]" not in contents
    assert "next_edges = []" not in contents
    assert "queue.pop(0)" not in contents
    assert "path + [edge]" not in contents


def test_explain_edge_returns_evidence_chain():
    graph = extract_project(PROJECT_PATH)
    resolved = resolve_precision(graph)
    
    res = explain_edge(
        resolved,
        from_symbol="services.OrderService.create_order",
        to_symbol="repositories.OrderRepository.save",
        kind="CALLS"
    )
    
    assert res["found"] is True
    edge = res["edge"]
    assert edge["from"] == "services.OrderService.create_order"
    assert edge["to"] == "repositories.OrderRepository.save"
    assert edge["kind"] == "CALLS"
    assert edge["source"] == "INFERRED"
    assert edge["confidence"] >= 0.80
    
    evidence = res["evidence"]
    assert len(evidence) >= 4
    
    # Ensure evidence descriptions have details of the inference chain
    descriptions = [ev["description"] for ev in evidence]
    assert any("OrderRepository" in d for d in descriptions)
    assert any("OrderService" in d for d in descriptions)
    assert any("repository" in d for d in descriptions)
