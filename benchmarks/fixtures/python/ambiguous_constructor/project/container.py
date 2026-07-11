from repositories import PrimaryRepository
from service import Service


def build():
    repository = PrimaryRepository()
    return Service(repository=repository)
