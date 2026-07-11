from pathlib import Path

from impact_engine.extractors.python_ast import extract_project
from impact_engine.resolution.engine import resolve_graph


def _write_project(root: Path) -> None:
    files = {
        "backend/app/api/routes.py": """
from fastapi import Depends
from app.controllers.order_controller import OrderController


def create_order_route(controller: OrderController = Depends()):
    return controller.create({})
""",
        "backend/app/controllers/order_controller.py": """
from app.services.order_service import OrderService


class OrderController:
    def __init__(self, order_service: OrderService):
        self._service_alias = order_service

    def create(self, payload):
        return self._service_alias.create_order(payload)
""",
        "backend/app/services/order_service.py": """
from app.repositories.order_repository import OrderRepository as RepoAlias


class OrderService:
    def __init__(self, repository: RepoAlias):
        self._repo_alias = repository

    def create_order(self, payload):
        return self._repo_alias.save(payload)
""",
        "backend/app/repositories/order_repository.py": """
from app.db.client import DatabaseClient as DbClientAlias


class OrderRepository:
    def __init__(self, db_client: DbClientAlias):
        self._client_alias = db_client

    def save(self, order_data):
        return self._client_alias.insert(order_data)
""",
        "backend/app/db/client.py": """
class DatabaseClient:
    def insert(self, order_data):
        return order_data
""",
    }
    for rel_path, content in files.items():
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.strip() + "\n", encoding="utf-8")


def test_realistic_di_chain_resolves_aliases_annotations_and_self_aliases(tmp_path):
    _write_project(tmp_path)

    graph = resolve_graph(extract_project(tmp_path))

    expected_edges = [
        (
            "backend.app.api.routes.create_order_route",
            "backend.app.controllers.order_controller.OrderController.create",
        ),
        (
            "backend.app.controllers.order_controller.OrderController.create",
            "backend.app.services.order_service.OrderService.create_order",
        ),
        (
            "backend.app.services.order_service.OrderService.create_order",
            "backend.app.repositories.order_repository.OrderRepository.save",
        ),
        (
            "backend.app.repositories.order_repository.OrderRepository.save",
            "backend.app.db.client.DatabaseClient.insert",
        ),
    ]

    for from_node, to_node in expected_edges:
        edge = next(
            (
                e
                for e in graph.edges
                if e.kind == "CALLS"
                and e.from_node == from_node
                and e.to_node == to_node
                and e.source == "INFERRED"
            ),
            None,
        )
        assert edge is not None, f"missing inferred edge: {from_node} -> {to_node}"
        assert edge.confidence >= 0.8
        assert edge.evidence
