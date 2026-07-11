"""Service layer for orders.

This is where business logic lives. The service depends on the OrderRepository
for persistence and exposes a small, intention-revealing API to the HTTP layer.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.repositories.orders import OrderRepository


class OrderService:
    """Apply business rules on top of the OrderRepository."""

    def __init__(self, repository: OrderRepository) -> None:
        self._repository = repository

    def create_order(self, payload: Any) -> dict:
        """Validate, compute totals and persist a new order."""
        items = [
            {
                "sku": item.sku,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
            }
            for item in payload.items
        ]
        total = sum(item["quantity"] * item["unit_price"] for item in items)
        order = {
            "id": f"ord_{uuid.uuid4().hex[:8]}",
            "customer_id": payload.customer_id,
            "items": items,
            "total": total,
            "status": "draft",
        }
        # Critical call: OrderRepository.save must be tracked by impact analysis.
        return self._repository.save(order)

    def checkout(self, order_id: str) -> dict | None:
        """Mark an order as paid and return the checkout summary."""
        order = self._repository.get(order_id)
        if order is None:
            return None
        order["status"] = "paid"
        self._repository.save(order)
        return {
            "order_id": order["id"],
            "status": order["status"],
            "payment_ref": f"pay_{uuid.uuid4().hex[:10]}",
        }
