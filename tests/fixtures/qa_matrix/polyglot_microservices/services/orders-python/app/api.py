from __future__ import annotations

from fastapi import APIRouter, Depends

from .repository import OrderRepository
from .service import OrderService

router = APIRouter()


def get_order_service() -> OrderService:
    return OrderService(OrderRepository())


@router.post("/orders")
def create_order(payload: dict, service: OrderService = Depends(get_order_service)) -> dict:
    return service.create_order(payload)
