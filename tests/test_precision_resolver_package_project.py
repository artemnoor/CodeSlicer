import pytest
from pathlib import Path
from impact_engine.extractors.python_ast import extract_project
from impact_engine.resolution.precision import resolve_precision

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "package_di_project"


def test_precision_resolver_package_project():
    graph = extract_project(FIXTURE_PATH)
    resolved = resolve_precision(graph)
    
    # Assert there is a CALLS edge from OrderService.create_order to OrderRepository.save
    edge = next(
        (e for e in resolved.edges if e.from_node == "app.services.order_service.OrderService.create_order"
         and e.to_node == "app.repositories.order_repository.OrderRepository.save"
         and e.kind == "CALLS"),
        None
    )
    assert edge is not None
    assert edge.source == "INFERRED"
    assert edge.confidence >= 0.80
    assert len(edge.evidence) >= 4
    
    # Print the evidence descriptions for debugging/reporting
    for idx, ev in enumerate(edge.evidence):
        print(f"Evidence {idx + 1}: {ev.description}")
