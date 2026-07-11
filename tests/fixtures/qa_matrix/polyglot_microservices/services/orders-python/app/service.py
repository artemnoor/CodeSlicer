from __future__ import annotations

from .repository import OrderRepository


class OrderService:
    def __init__(self, repository: OrderRepository) -> None:
        self.repository = repository

    def create_order(self, payload: dict) -> dict:
        order = {
            "id": payload.get("id", "ord_test_1"),
            "items": payload.get("items", []),
            "source": "orders-python",
        }
        saved_order = self.repository.save(order)
        return {"status": "created", "order": saved_order}

    def save(self, payload: dict) -> dict:
        """Trap method: same name as repository.save but not part of route chain."""
        return {"status": "service-save-trap", "payload": payload}
