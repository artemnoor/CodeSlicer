from repositories import OrderRepository
from services import OrderService


class Container:
    def __init__(self):
        self.order_repository = OrderRepository()
        self.order_service = OrderService(repository=self.order_repository)
