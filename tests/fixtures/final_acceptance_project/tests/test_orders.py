from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_create_order():
    response = client.post("/api/orders/", json={"item": "pizza"})
    assert response.status_code == 200
