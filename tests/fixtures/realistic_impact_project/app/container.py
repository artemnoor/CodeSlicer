from repositories.order_repository import OrderRepository
from adapters.email_adapter import EmailAdapter
from services.order_service import OrderService


class Container:
    def __init__(self):
        self.repository = OrderRepository()
        self.email_adapter = EmailAdapter()
        self.order_service = OrderService(
            repository=self.repository,
            email_adapter=self.email_adapter
        )
