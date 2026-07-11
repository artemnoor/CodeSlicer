from fastapi import APIRouter, Depends
from app.services import OrderService

router = APIRouter(prefix="/orders")

class Container:
    def __init__(self):
        self.service = OrderService()

container = Container()

def get_order_service():
    return container.service

@router.post("/")
def create_order(order_data: dict, service: OrderService = Depends(get_order_service)):
    return service.create_order(order_data)
