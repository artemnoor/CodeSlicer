class OrderRepository:
    def save(self, order: dict) -> dict:
        return {"id": "order-1", **order}
