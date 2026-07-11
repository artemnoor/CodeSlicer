from repository import Repository


class Service:
    def __init__(self):
        self.repository = Repository()

    def create(self, value):
        return self.repository.save(value)
