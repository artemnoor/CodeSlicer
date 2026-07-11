from pathlib import Path

from impact_engine.analysis.pipeline import analyze_project_core


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_semantic_layer_resolves_nested_router_and_frontend_endpoint(tmp_path):
    project = tmp_path / "semantic_project"
    _write(project / "backend" / "app" / "api" / "orders.py", """
from fastapi import APIRouter

orders_router = APIRouter(prefix="/orders")

@orders_router.post("/")
def create_order(payload):
    return {"ok": True}
""")
    _write(project / "backend" / "app" / "api" / "users.py", """
from fastapi import APIRouter

admin_router = APIRouter(prefix="/admin")
accounts_router = APIRouter(prefix="/accounts")
admin_router.include_router(accounts_router)

@accounts_router.get("/{user_id}")
def get_admin_user(user_id: str):
    return {"id": user_id}
""")
    _write(project / "backend" / "app" / "main.py", """
from fastapi import APIRouter, FastAPI
from backend.app.api.orders import orders_router
from backend.app.api.users import admin_router

app = FastAPI()
api_router = APIRouter(prefix="/api")
api_router.include_router(orders_router)
api_router.include_router(admin_router)
app.include_router(api_router)
""")
    _write(project / "frontend" / "api.ts", """
export function postJson(path: string, payload: unknown) {
  return fetch(path, { method: "POST", body: JSON.stringify(payload) });
}

export function getJson(path: string) {
  return fetch(path, { method: "GET" });
}
""")
    _write(project / "frontend" / "orders.ts", """
import { postJson, getJson } from "./api";

export function createOrder(payload: unknown) {
  return postJson("/api/orders/", payload);
}

export function getOrder(id: string) {
  return getJson(`/api/orders/${id}`);
}
""")

    result = analyze_project_core(str(project))
    edges = result["graph"]["edges"]

    assert any(
        edge["kind"] == "ROUTE_HANDLES"
        and edge["from"] == "HTTP POST /api/orders"
        and edge["to"].endswith("backend.app.api.orders.create_order")
        and edge["confidence"] >= 0.9
        and edge["evidence"]
        for edge in edges
    )
    assert any(
        edge["kind"] == "ROUTE_HANDLES"
        and edge["from"] == "HTTP GET /api/admin/accounts/{user_id}"
        and edge["to"].endswith("backend.app.api.users.get_admin_user")
        for edge in edges
    )
    assert any(
        edge["kind"] == "HTTP_CALLS"
        and edge["from"] == "createOrder"
        and edge["to"] == "HTTP POST /api/orders"
        and edge["confidence"] >= 0.9
        for edge in edges
    )
    assert any(
        edge["kind"] == "MATCHES_ENDPOINT"
        and edge["from"] == "createOrder"
        and edge["to"].endswith("backend.app.api.orders.create_order")
        and edge["confidence"] >= 0.8
        and edge["evidence"]
        for edge in edges
    )

    semantic_meta = result["graph"]["metadata"]["semantic_binding_layer"]
    assert semantic_meta["status"] == "applied"
    assert semantic_meta["facts"]["decorators"] >= 2
