from fastapi.testclient import TestClient

from app.main import app
from app.repository import OrderRepository
from app.service import OrderService


def test_create_order_route_hits_service_chain() -> None:
    client = TestClient(app)

    response = client.post("/api/orders", json={"id": "ord_42", "items": ["book"]})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "created"
    assert body["order"]["id"] == "ord_42"
    assert body["order"]["persisted"] is True


def test_order_service_calls_repository_save() -> None:
    repository = OrderRepository()
    service = OrderService(repository)

    result = service.create_order({"id": "ord_direct", "items": []})

    assert result["order"]["persisted"] is True
    assert repository._orders[0]["id"] == "ord_direct"
