from repositories import PrimaryRepository


class Service:
    def __init__(self, repository: PrimaryRepository):
        self.repository = repository

    def create(self, value):
        return self.repository.save(value)
