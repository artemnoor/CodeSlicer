from repository import Repository
def get_repository() -> Repository:
    return Repository()
def create(value):
    repository = get_repository()
    return repository.save(value)
