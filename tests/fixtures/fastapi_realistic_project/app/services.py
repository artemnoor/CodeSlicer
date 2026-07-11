from app.repositories import OrderRepository

class OrderService:
    def __init__(self, repository: OrderRepository):
        self.repository = repository

    def create_order(self, data: dict):
        # Business logic
        return self.repository.save(data)
