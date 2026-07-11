import pytest
from pathlib import Path
from impact_engine.extractors.python_ast import extract_project
from impact_engine.resolution.precision import resolve_precision

PROJECT_PATH = Path(__file__).parent.parent / "examples" / "golden_cases" / "python_di_basic"


def test_resolver_creates_main_inferred_edge():
    graph = extract_project(PROJECT_PATH)
    resolved = resolve_precision(graph)
    
    # Assert a CALLS edge exists between service create_order and repository save
    calls_edge = next(
        (e for e in resolved.edges if e.kind == "CALLS" and e.from_node == "services.OrderService.create_order" and e.to_node == "repositories.OrderRepository.save"),
        None
    )
    
    assert calls_edge is not None, "Inferred CALLS edge not found"
    assert calls_edge.source == "INFERRED"
    assert calls_edge.confidence >= 0.80
    assert len(calls_edge.evidence) > 0


def test_resolver_evidence_chain_contains_required_steps():
    graph = extract_project(PROJECT_PATH)
    resolved = resolve_precision(graph)
    
    calls_edge = next(
        (e for e in resolved.edges if e.kind == "CALLS" and e.from_node == "services.OrderService.create_order" and e.to_node == "repositories.OrderRepository.save"),
        None
    )
    assert calls_edge is not None
    
    # Gather all evidence descriptions
    evidence_descriptions = [ev.description for ev in calls_edge.evidence]
    evidence_text = " | ".join(evidence_descriptions)
    
    # Assert final edge evidence descriptions include references to:
    # - self.order_repository
    # - OrderRepository
    # - OrderService
    # - repository=self.order_repository
    # - self.repository = repository
    # - self.repository.save
    assert "self.order_repository" in evidence_text
    assert "OrderRepository" in evidence_text
    assert "OrderService" in evidence_text
    assert "repository=self.order_repository" in evidence_text
    assert "self.repository = repository" in evidence_text
    assert "self.repository.save" in evidence_text


def test_resolver_preserves_extracted_nodes_and_edges():
    graph = extract_project(PROJECT_PATH)
    
    num_nodes_before = len(graph.nodes)
    num_edges_before = len(graph.edges)
    
    resolved = resolve_precision(graph)
    
    # Resolver should not delete any extracted nodes or edges
    num_nodes_after = len(resolved.nodes)
    num_edges_after = len(resolved.edges)
    
    assert num_nodes_after >= num_nodes_before
    assert num_edges_after >= num_edges_before
    
    # Check that critical extracted node still exists
    assert any(n.id == "class:services.OrderService" for n in resolved.nodes)


def test_resolver_does_not_create_ai_proposed_edges():
    graph = extract_project(PROJECT_PATH)
    resolved = resolve_precision(graph)
    
    for edge in resolved.edges:
        assert edge.source != "AI_PROPOSED", "No edges should be proposed by AI at this stage"
