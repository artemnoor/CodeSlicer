class OrderRepository:
    def save(self, data):
        return {"status": "saved", "data": data}
