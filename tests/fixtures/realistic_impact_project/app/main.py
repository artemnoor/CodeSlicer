from app.container import Container
from domain.order import Order


def run():
    container = Container()
    order = Order("order_123")
    container.order_service.place_order(order)
