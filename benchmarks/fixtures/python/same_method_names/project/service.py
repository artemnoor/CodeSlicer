from repositories import OrderRepository


class Service:
    def __init__(self):
        self.repository = OrderRepository()

    def create(self, value):
        return self.repository.save(value)
