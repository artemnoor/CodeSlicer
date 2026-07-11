from repository import Repository


class Service:
    def create(self, value):
        repository = Repository()
        return repository.save(value)
