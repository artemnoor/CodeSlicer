from app.repositories import OrderRepository

class OrderService:
    def __init__(self):
        self.repository = OrderRepository()

    def create_order(self, data: dict):
        return self.repository.save(data)
