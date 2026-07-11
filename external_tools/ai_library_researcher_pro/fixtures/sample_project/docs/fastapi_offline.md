# FastAPI offline fixture

A small official-style fixture used by tests when live network is disabled.

```python
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

router = APIRouter(prefix="/orders")

class OrderRepository:
    def save(self, payload: dict) -> dict:
        return {"id": "ord_1", **payload}

class OrderService:
    def __init__(self, repository: OrderRepository):
        self.repository = repository

    def create_order(self, payload: dict) -> dict:
        return self.repository.save(payload)

def get_service() -> OrderService:
    return OrderService(OrderRepository())

@router.post("/")
def create_order(payload: dict, service: OrderService = Depends(get_service)):
    return service.create_order(payload)

app = FastAPI()
app.include_router(router)

client = TestClient(app)

def test_create_order():
    response = client.post("/orders/", json={"sku": "A"})
    assert response.status_code == 200
```
