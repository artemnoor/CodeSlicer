from fastapi import APIRouter, Depends
from app.container import Container
from app.services import OrderService

router = APIRouter(prefix="/orders")

def get_order_service() -> OrderService:
    container = Container()
    return container.order_service()

@router.post("/")
def create_order(order_data: dict, service: OrderService = Depends(get_order_service)):
    return service.create_order(order_data)
