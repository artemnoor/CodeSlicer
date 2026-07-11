"""Local repository. Imports from app.* should not be treated as unknown."""

from __future__ import annotations

from typing import Any


class OrderRepository:
    """In-memory repository used to make the test deterministic."""

    def __init__(self) -> None:
        self._orders: list[dict[str, Any]] = []

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        order = {
            "id": f"order-{len(self._orders) + 1}",
            "status": payload.get("status", "created"),
            "payload": dict(payload),
        }
        self._orders.append(order)
        return order

    @property
    def orders(self) -> list[dict[str, Any]]:
        return list(self._orders)
