class OrderRepository:
    def save(self, data: dict):
        return {"status": "saved", "data": data}
