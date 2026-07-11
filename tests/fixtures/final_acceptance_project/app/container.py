from dependency_injector import containers, providers
from app.repositories import OrderRepository
from app.services import OrderService

class Container(containers.DeclarativeContainer):
    repository = providers.Singleton(OrderRepository, "sqlite://")
    order_service = providers.Factory(OrderService, repository=repository)
