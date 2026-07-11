from repositories import OrderRepository, UnitOfWork
from service import Service


def build():
    orders = OrderRepository()
    uow = UnitOfWork(orders=orders)
    return Service(uow=uow)
