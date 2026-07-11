from app.repositories.orders import OrderRepository


class OrderService:
    def __init__(self) -> None:
        self.repository = OrderRepository()

    def create_order(self, payload: dict) -> dict:
        return self.repository.save(payload)
