class OrderRepository:
    def save(self, value):
        return value


class OtherRepository:
    def save(self, value):
        return value


class UnitOfWork:
    def __init__(self, orders: OrderRepository):
        self.orders = orders
