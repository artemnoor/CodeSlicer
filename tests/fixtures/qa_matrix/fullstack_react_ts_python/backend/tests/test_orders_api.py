"""End-to-end tests for the orders API chain.

These tests exercise the full prefix chain:
    /api/v1/shop/orders
    /api/v1/shop/orders/{order_id}/checkout

They also verify the users route works independently.
"""

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_create_order_returns_201_and_persists() -> None:
    payload = {
        "customer_id": "cust_1",
        "items": [
            {"sku": "A", "quantity": 2, "unit_price": 5.0},
            {"sku": "B", "quantity": 1, "unit_price": 10.0},
        ],
    }
    response = client.post("/api/v1/shop/orders", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["customer_id"] == "cust_1"
    assert body["total"] == 20.0
    assert body["status"] == "draft"
    assert body["id"].startswith("ord_")


def test_checkout_order_after_create_returns_paid() -> None:
    create = client.post(
        "/api/v1/shop/orders",
        json={
            "customer_id": "cust_2",
            "items": [{"sku": "X", "quantity": 3, "unit_price": 2.0}],
        },
    )
    order_id = create.json()["id"]

    response = client.post(f"/api/v1/shop/orders/{order_id}/checkout")

    assert response.status_code == 200
    body = response.json()
    assert body["order_id"] == order_id
    assert body["status"] == "paid"
    assert body["payment_ref"].startswith("pay_")


def test_checkout_unknown_order_returns_404() -> None:
    response = client.post("/api/v1/shop/orders/ord_missing/checkout")
    assert response.status_code == 404


def test_create_user_is_independent_of_orders() -> None:
    response = client.post(
        "/api/v1/shop/users",
        json={"name": "Alice", "email": "alice@example.com"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Alice"
    assert body["email"] == "alice@example.com"
    assert body["id"].startswith("usr_")


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
