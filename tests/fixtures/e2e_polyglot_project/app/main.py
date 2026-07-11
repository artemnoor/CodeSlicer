from fastapi import FastAPI
from app.services import OrderService
from app.repositories import OrderRepository

app = FastAPI()

class Container:
    def __init__(self):
        self.repo = OrderRepository()
        self.service = OrderService(repository=self.repo)

container = Container()

@app.post("/orders")
def create_order_endpoint(order_data: dict):
    return container.service.create_order(order_data)
