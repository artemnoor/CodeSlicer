from pathlib import Path

from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.models import GraphDocument
from impact_engine.nested_object_graph import build_nested_object_graph_input


def _write_project(root: Path) -> None:
    (root / "app").mkdir()
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "app" / "repositories.py").write_text(
        """
class OrderRepository:
    def save(self, order):
        return order

    def find_by_id(self, order_id):
        return {"id": order_id}

    def mark_paid(self, order_id):
        return {"id": order_id, "paid": True}


class OrderUnitOfWork:
    def __init__(self, orders: OrderRepository):
        self.orders = orders

    def commit(self):
        return None
""",
        encoding="utf-8",
    )
    (root / "app" / "services.py").write_text(
        """
from app.repositories import OrderRepository, OrderUnitOfWork


class PaymentService:
    def charge_for_order(self, order):
        return {"charged": order}


class OrderService:
    def __init__(self, repository: OrderRepository, uow: OrderUnitOfWork, payment_service: PaymentService):
        self.repository = repository
        self.primary_repo_alias = self.repository
        self.uow = uow
        self.payment_service = payment_service
        self.nested_alias = {"orders": repository}

    def create_order(self, order):
        return self.repository.save(order)

    def complete_checkout(self, order_id):
        order = self.uow.orders.find_by_id(order_id)
        self.uow.orders.mark_paid(order_id)
        self.uow.commit()
        self.payment_service.charge_for_order(order)

    def create_order_through_nested_alias(self, order):
        return self.nested_alias["orders"].save(order)
""",
        encoding="utf-8",
    )


def test_nested_object_graph_resolver_integrates_with_pipeline(tmp_path: Path):
    _write_project(tmp_path)

    result = analyze_project_core(str(tmp_path))
    graph = GraphDocument.from_dict(result["graph"])

    assert graph.metadata["nested_object_graph_resolver"]["status"] == "applied"

    expected = {
        ("app.services.OrderService.create_order", "app.repositories.OrderRepository.save"),
        ("app.services.OrderService.complete_checkout", "app.repositories.OrderRepository.find_by_id"),
        ("app.services.OrderService.complete_checkout", "app.repositories.OrderRepository.mark_paid"),
        ("app.services.OrderService.complete_checkout", "app.repositories.OrderUnitOfWork.commit"),
        ("app.services.OrderService.complete_checkout", "app.services.PaymentService.charge_for_order"),
        ("app.services.OrderService.create_order_through_nested_alias", "app.repositories.OrderRepository.save"),
    }
    actual = {
        (edge.from_node, edge.to_node)
        for edge in graph.edges
        if edge.kind == "CALLS" and edge.properties.get("resolver") == "nested_object_graph_resolver"
    }

    assert expected <= actual


def test_nested_object_graph_input_contains_dict_bindings(tmp_path: Path):
    _write_project(tmp_path)

    result = analyze_project_core(str(tmp_path))
    graph = GraphDocument.from_dict(result["graph"])
    facts = build_nested_object_graph_input(graph)

    assert any(binding.get("target") == "self.nested_alias" for binding in facts["dict_bindings"])
