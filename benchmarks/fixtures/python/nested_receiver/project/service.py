from repositories import UnitOfWork


class Service:
    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    def create(self, value):
        return self.uow.orders.save(value)
