import pytest
from pathlib import Path
from impact_engine.extractors.python_ast import extract_project
from impact_engine.resolution.precision import resolve_precision
from impact_engine.impact import impact_query, explain_edge

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
