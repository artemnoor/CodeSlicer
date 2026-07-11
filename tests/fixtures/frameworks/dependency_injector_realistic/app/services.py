class OrderService:
    def __init__(self, repository):
        self.repository = repository

    def create_order(self, data):
        return self.repository.save(data)
