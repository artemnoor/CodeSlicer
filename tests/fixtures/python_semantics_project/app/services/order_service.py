class OrderService:
    def __init__(self, repository):
        self.repository = repository
        self.repo = repository
        
    def create_order(self, order):
        self._persist_order(order)
        
    def _persist_order(self, order):
        self.repo.save(order)

    def persist_order_alias(self, order):
        return self.repo.save(order)
