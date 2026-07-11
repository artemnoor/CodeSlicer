"""``/api/v1/shop/orders`` routes.

Each handler is intentionally **thin** — all real logic lives in
``OrderService``. This makes the impact chain easy to follow:

    POST /api/v1/shop/orders
        -> create_order (this module)
        -> OrderService.create_order
        -> OrderRepository.save   (via self.repositories["orders"])

    POST /api/v1/shop/orders/{order_id}/checkout
        -> create_checkout (this module)
        -> OrderService.complete_checkout
        -> OrderUnitOfWork.orders.find_by_id
        -> OrderUnitOfWork.orders.mark_paid
        -> PaymentService.charge_for_order
        -> BillingRepository.save_payment_attempt
        -> OrderUnitOfWork.commit
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_order_service
from app.services.orders import OrderService

# NOTE: this module defines ``router = APIRouter(...)``. The ``users``
# module also defines a variable named ``router`` — that is intentional,
# to exercise the "router variable collision" trap for static analyzers.
router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("")
def create_order(
    payload: Dict[str, Any],
    order_service: OrderService = Depends(get_order_service),
) -> Dict[str, Any]:
    """Create a new order. Thin wrapper around ``OrderService.create_order``."""
    return order_service.create_order(payload)


@router.post("/{order_id}/checkout")
def create_checkout(
    order_id: str,
    order_service: OrderService = Depends(get_order_service),
) -> Dict[str, Any]:
    """Checkout an existing order. Thin wrapper around
    ``OrderService.complete_checkout``."""
    try:
        return order_service.complete_checkout(order_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{order_id}")
def get_order(
    order_id: str,
    order_service: OrderService = Depends(get_order_service),
) -> Dict[str, Any]:
    order = order_service.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
    return order
