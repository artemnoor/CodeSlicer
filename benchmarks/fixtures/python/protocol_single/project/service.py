from repo import Repository
class Service:
    def __init__(self, repository: Repository): self.repository = repository
    def create(self, value): return self.repository.save(value)
