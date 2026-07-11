class Service:
    def __init__(self, repository): self.repository = repository
    def create(self, value): return self.repository.save(value)
