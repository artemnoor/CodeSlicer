from dependency_injector import containers, providers
from app.repositories import OrderRepository
from app.services import OrderService

class Container(containers.DeclarativeContainer):
    order_repository = providers.Singleton(OrderRepository)
    order_service = providers.Factory(OrderService, repository=order_repository)
