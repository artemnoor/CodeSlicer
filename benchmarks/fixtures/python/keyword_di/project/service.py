from repo import Repository
class Container:
    def __init__(self):
        self.repository = Repository()
        self.service = Service(repository=self.repository)

class Service:
    def __init__(self, repository): self.repository = repository
    def create(self, value): return self.repository.save(value)
