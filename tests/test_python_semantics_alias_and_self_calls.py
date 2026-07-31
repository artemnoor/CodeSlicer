import pytest
from pathlib import Path
from impact_engine.extractors.python_ast import extract_project
from impact_engine.resolution.engine import resolve_graph

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "python_semantics_project"


def test_python_semantics_alias_and_self_calls():
    graph = extract_project(FIXTURE_PATH)
    resolved = resolve_graph(graph)
    
    # 1. Assert create_order -> _persist_order
    edge_self = next(
        (e for e in resolved.edges if e.from_node == "app.services.order_service.OrderService.create_order"
         and e.to_node == "app.services.order_service.OrderService._persist_order"
         and e.kind == "CALLS"),
        None
    )
    assert edge_self is not None
    assert edge_self.source == "INFERRED"
    assert edge_self.confidence >= 0.90
    assert len(edge_self.evidence) > 0
    print(f"\nSelf call edge evidence: {[ev.description for ev in edge_self.evidence]}")

    # 2. Assert _persist_order -> OrderRepository.save
    edge_repo = next(
        (e for e in resolved.edges if e.from_node == "app.services.order_service.OrderService._persist_order"
         and e.to_node == "app.repositories.order_repository.OrderRepository.save"
         and e.kind == "CALLS"),
        None
    )
    assert edge_repo is not None
    assert edge_repo.source == "INFERRED"
    assert edge_repo.confidence >= 0.80
    assert len(edge_repo.evidence) > 0
    print(f"Alias field call edge evidence: {[ev.description for ev in edge_repo.evidence]}")

    # 3. Assert persist_order_alias -> OrderRepository.save
    edge_alias = next(
        (e for e in resolved.edges if e.from_node == "app.services.order_service.OrderService.persist_order_alias"
         and e.to_node == "app.repositories.order_repository.OrderRepository.save"
         and e.kind == "CALLS"),
        None
    )
    assert edge_alias is not None
    assert edge_alias.source == "INFERRED"
    assert edge_alias.confidence >= 0.80
    assert len(edge_alias.evidence) > 0
    print(f"Direct persist_order_alias edge evidence: {[ev.description for ev in edge_alias.evidence]}")


def test_python_annotated_bindings_and_local_aliases_are_resolved_conservatively(tmp_path: Path):
    """Typed fields and aliases are common, while rebindings must not guess."""
    (tmp_path / "domain.py").write_text(
        """
class PrimaryRepository:
    def save(self, value):
        return value


class SecondaryRepository:
    def save(self, value):
        return value
""",
        encoding="utf-8",
    )
    (tmp_path / "service.py").write_text(
        """
from .domain import PrimaryRepository, SecondaryRepository


class Service:
    def __init__(self, repository: PrimaryRepository):
        self.repository: PrimaryRepository = repository

    def persist(self, value):
        active_repository = self.repository
        return active_repository.save(value)

    def dynamically_rebound(self, value):
        target = PrimaryRepository()
        target = SecondaryRepository()
        return target.save(value)
""",
        encoding="utf-8",
    )

    graph = resolve_graph(extract_project(tmp_path))
    calls = {(edge.from_node, edge.to_node) for edge in graph.edges if edge.kind == "CALLS"}

    assert (
        "service.Service.persist",
        "domain.PrimaryRepository.save",
    ) in calls
    assert not any(
        source == "service.Service.dynamically_rebound" and target.endswith("Repository.save")
        for source, target in calls
    )
