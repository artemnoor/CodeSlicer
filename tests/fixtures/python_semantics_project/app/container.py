from app.repositories.order_repository import OrderRepository
from app.services.order_service import OrderService


class Container:
    def __init__(self):
        self.order_repository = OrderRepository()
        self.order_service = OrderService(repository=self.order_repository)
