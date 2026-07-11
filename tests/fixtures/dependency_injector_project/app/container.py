from dependency_injector import containers, providers
from app.repositories import SqlRepository
from app.services import DataService

class Container(containers.DeclarativeContainer):
    repository = providers.Singleton(SqlRepository)
    service = providers.Factory(DataService, repository=repository)
