"""Payment service.

Called by ``OrderService.complete_checkout``. Internally persists a
payment attempt via ``BillingRepository.save_payment_attempt``.
"""
from __future__ import annotations

from typing import Any, Dict

from app.repositories.billing import BillingRepository


class PaymentService:
    def __init__(self, billing_repository: BillingRepository) -> None:
        self.billing_repository = billing_repository

    def charge_for_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        attempt: Dict[str, Any] = {
            "order_id": order["id"],
            "amount": float(order.get("total", 0)),
            "currency": order.get("currency", "USD"),
            "status": "succeeded",
        }
        self.billing_repository.save_payment_attempt(attempt)
        return attempt
