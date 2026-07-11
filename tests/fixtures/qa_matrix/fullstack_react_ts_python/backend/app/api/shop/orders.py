"""HTTP routes for shop orders.

Chain:
    POST /api/v1/shop/orders              -> create_order -> OrderService.create_order -> OrderRepository.save
    POST /api/v1/shop/orders/{order_id}/checkout -> checkout_order -> OrderService.checkout
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.services.orders import OrderService
from app.repositories.orders import OrderRepository


orders_router = APIRouter()


class OrderItemIn(BaseModel):
    """A single line item submitted by the client when creating an order."""

    sku: str = Field(..., min_length=1)
    quantity: int = Field(..., gt=0)
    unit_price: float = Field(..., ge=0)


class OrderCreateIn(BaseModel):
    """Payload accepted by POST /api/v1/shop/orders."""

    customer_id: str = Field(..., min_length=1)
    items: list[OrderItemIn] = Field(..., min_length=1)


class OrderOut(BaseModel):
    """Order representation returned to the client."""

    id: str
    customer_id: str
    total: float
    status: str


class CheckoutOut(BaseModel):
    """Result of the checkout operation."""

    order_id: str
    status: str
    payment_ref: str


# Inject repository into service. In a real app this would be a DI container.
_order_repository = OrderRepository()
_order_service = OrderService(repository=_order_repository)


@orders_router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderCreateIn) -> OrderOut:
    """Create a new order and persist it through OrderRepository.save."""
    order = _order_service.create_order(payload)
    return OrderOut(**order)


@orders_router.post("/{order_id}/checkout", response_model=CheckoutOut)
def checkout_order(order_id: str) -> CheckoutOut:
    """Checkout an existing order via OrderService.checkout."""
    result = _order_service.checkout(order_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
    return CheckoutOut(**result)
