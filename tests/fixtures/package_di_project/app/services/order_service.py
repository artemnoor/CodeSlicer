class OrderService:
    def __init__(self, repository):
        self.repository = repository
        
    def create_order(self, order):
        self.repository.save(order)
