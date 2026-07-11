"""Order service.

``OrderService`` is the orchestrator for both the *create order* and
*checkout* flows. Two deliberate traps are embedded here for the
impact-analysis system:

1. ``self.repositories["orders"]`` is a dict-style alias that points at
   ``self.uow.orders``. A naive static analyzer that only follows direct
   attribute access will miss the call to ``OrderRepository.save``.
2. ``self.nested_alias["orders"]`` is a second alias used by
   :meth:`refresh_order`. The analyzer must follow both alias paths to
   correctly resolve all callers of ``OrderRepository.save``.

``LegacyOrderRepository`` is **never** referenced here.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.audit import AuditService
from app.services.payments import PaymentService
from app.uow import OrderUnitOfWork


class OrderService:
    def __init__(
        self,
        uow: OrderUnitOfWork,
        payment_service: PaymentService,
        audit_service: AuditService,
    ) -> None:
        self.uow = uow
        self.payment_service = payment_service
        self.audit_service = audit_service

        # Alias-trap #1: dict-style indirection on the active repository.
        self.repositories: Dict[str, Any] = {"orders": uow.orders}
        # Alias-trap #2: a second, differently-named alias on the same object.
        self.nested_alias: Dict[str, Any] = {"orders": uow.orders}

    # ------------------------------------------------------------------ create
    def create_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Build an order dict and persist it via the active repository.

        Uses ``self.repositories["orders"].save(order)`` deliberately to
        exercise the dict-alias impact-analysis trap.
        """
        order: Dict[str, Any] = {
            "id": order_data["id"],
            "user_id": order_data["user_id"],
            "items": list(order_data.get("items", [])),
            "status": "created",
            "total": float(order_data.get("total", 0)),
        }
        # Alias-trap #1: routes through `self.repositories["orders"]`,
        # which resolves to `OrderRepository.save` at runtime.
        saved = self.repositories["orders"].save(order)

        self.audit_service.log({"event": "order_created", "order_id": order["id"]})
        return saved

    def refresh_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """Re-save an order via the *other* alias to test nested_alias trap."""
        # Alias-trap #2: routes through `self.nested_alias["orders"]`,
        # which must resolve to the same `OrderRepository.save`.
        return self.nested_alias["orders"].save(order)

    # ---------------------------------------------------------------- checkout
    def complete_checkout(self, order_id: str) -> Dict[str, Any]:
        """Drive the full checkout chain.

        Expected call order:
            1. ``self.uow.orders.find_by_id``
            2. ``self.payment_service.charge_for_order``
               (which internally calls ``BillingRepository.save_payment_attempt``)
            3. ``self.uow.orders.mark_paid``
            4. ``self.uow.commit``
        """
        order = self.uow.orders.find_by_id(order_id)
        if order is None:
            raise ValueError(f"Order {order_id!r} not found")

        payment = self.payment_service.charge_for_order(order)

        self.uow.orders.mark_paid(order_id)

        self.uow.commit()

        self.audit_service.log(
            {"event": "order_checked_out", "order_id": order_id, "payment": payment}
        )
        return {
            "order_id": order_id,
            "status": "paid",
            "payment": payment,
        }

    # ------------------------------------------------------------------ query
    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        return self.uow.orders.find_by_id(order_id)
