from repo import Repository
class Service:
    def __init__(self): self.repositories = {"orders": Repository()}
    def create(self, value): return self.repositories["orders"].save(value)
