from fastapi import APIRouter

from app.services.orders import OrderService

router = APIRouter(prefix="/orders")


@router.post("")
def create_order(payload: dict) -> dict:
    return OrderService().create_order(payload)
