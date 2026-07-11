class LegacyOrderRepository:
    def save(self, order):
        return {"legacy": True, "order": order}


class OrderRepository:
    def save(self, order):
        return {"saved": True, "order": order}
