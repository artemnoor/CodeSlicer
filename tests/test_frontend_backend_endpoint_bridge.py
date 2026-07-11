import json
from pathlib import Path

from frontend_backend_endpoint_resolver.fixtures import fullstack_shop_fixture

from impact_engine.frontend_backend_bridge import apply_frontend_backend_endpoint_bridge
from impact_engine.models import Edge, Evidence, GraphDocument, Node


def _graph_with_endpoint_facts() -> GraphDocument:
    graph = GraphDocument(metadata={"frontend_backend_endpoint_facts": fullstack_shop_fixture()})
    graph.add_node(Node(id="HTTP POST /api/v1/shop/orders", kind="ROUTE", name="HTTP POST /api/v1/shop/orders"))
    graph.add_node(
        Node(
            id="HTTP POST /api/v1/shop/orders/{order_id}/checkout",
            kind="ROUTE",
            name="HTTP POST /api/v1/shop/orders/{order_id}/checkout",
        )
    )
    graph.add_node(Node(id="HTTP POST /api/v1/shop/users", kind="ROUTE", name="HTTP POST /api/v1/shop/users"))
    graph.add_edge(
        Edge(
            id="route_orders",
            kind="ROUTE_HANDLES",
            from_node="HTTP POST /api/v1/shop/orders",
            to_node="backend.app.api.orders.create_order",
            source="SUPPORT_PACK",
            confidence=0.9,
            evidence=[Evidence(description="fixture route")],
        )
    )
    graph.add_edge(
        Edge(
            id="route_checkout",
            kind="ROUTE_HANDLES",
            from_node="HTTP POST /api/v1/shop/orders/{order_id}/checkout",
            to_node="backend.app.api.orders.checkout_order",
            source="SUPPORT_PACK",
            confidence=0.9,
            evidence=[Evidence(description="fixture route")],
        )
    )
    graph.add_edge(
        Edge(
            id="route_users",
            kind="ROUTE_HANDLES",
            from_node="HTTP POST /api/v1/shop/users",
            to_node="backend.app.api.users.create_user",
            source="SUPPORT_PACK",
            confidence=0.9,
            evidence=[Evidence(description="fixture route")],
        )
    )
    return graph


def test_frontend_backend_endpoint_bridge_adds_schema_valid_edges():
    graph = apply_frontend_backend_endpoint_bridge(_graph_with_endpoint_facts())

    assert graph.metadata["frontend_backend_endpoint_bridge"]["status"] == "applied"

    assert any(
        edge.kind == "HTTP_CALLS"
        and edge.from_node == "frontend.ordersClient.createOrder"
        and edge.to_node == "HTTP POST /api/v1/shop/orders"
        and edge.confidence >= 0.84
        for edge in graph.edges
    )
    assert any(
        edge.kind == "HTTP_CALLS"
        and edge.from_node == "frontend.ordersClient.createOrder"
        and edge.to_node == "HTTP POST /api/v1/shop/orders"
        for edge in graph.edges
    )
    assert any(
        edge.kind == "HTTP_CALLS"
        and edge.from_node == "frontend.ordersClient.checkoutOrder"
        and edge.to_node == "HTTP POST /api/v1/shop/orders/{param}/checkout"
        and edge.confidence >= 0.84
        for edge in graph.edges
    )
    assert any(
        edge.kind == "MATCHES_ENDPOINT"
        and edge.from_node == "HTTP POST /api/v1/shop/orders"
        and edge.to_node == "backend.app.api.orders.create_order"
        for edge in graph.edges
    )
    assert not any(
        edge.properties.get("resolver") == "frontend_backend_endpoint_bridge"
        and edge.to_node == "backend.app.api.users.create_user"
        for edge in graph.edges
    )


def test_frontend_backend_endpoint_bridge_skips_without_frontend_facts():
    graph = GraphDocument()
    graph.add_node(Node(id="HTTP POST /orders", kind="ROUTE", name="HTTP POST /orders"))

    resolved = apply_frontend_backend_endpoint_bridge(graph)

    assert resolved.metadata["frontend_backend_endpoint_bridge"]["status"] == "skipped"


def test_frontend_backend_endpoint_bridge_result_is_json_serializable():
    graph = apply_frontend_backend_endpoint_bridge(_graph_with_endpoint_facts())

    json.dumps(graph.to_dict())


def test_endpoint_bridge_resolves_optional_parameter_ternary_paths():
    from frontend_backend_endpoint_resolver import resolve_frontend_backend_endpoints

    result = resolve_frontend_backend_endpoints({
        "modules": [
            {
                "id": "lib.routes",
                "constants": [{"id": "lib.routes.ORDER_PREFIX", "name": "ORDER_PREFIX", "module": "lib.routes", "expression": {"type": "literal", "value": "/api/v1/shop/orders"}}],
                "functions": [{
                    "id": "lib.routes.orderPath",
                    "name": "orderPath",
                    "module": "lib.routes",
                    "params": ["orderId"],
                    "returns": {
                        "type": "conditional",
                        "condition": {"type": "ref", "name": "orderId"},
                        "when_true": {"type": "template", "parts": [{"type": "ref", "name": "ORDER_PREFIX"}, {"type": "literal", "value": "/"}, {"type": "ref", "name": "orderId"}]},
                        "when_false": {"type": "ref", "name": "ORDER_PREFIX"},
                    },
                }],
            }
        ],
        "frontend_functions": [
            {"id": "api.orders.createOrder", "module": "api.orders", "calls": [{"callee": "postJson", "args": [{"type": "call", "name": "lib.routes.orderPath", "args": []}, {"type": "object", "properties": {}}]}]},
            {"id": "api.orders.getOrder", "module": "api.orders", "params": ["orderId"], "calls": [{"callee": "postJson", "args": [{"type": "call", "name": "lib.routes.orderPath", "args": [{"type": "ref", "name": "orderId"}]}, {"type": "object", "properties": {}}]}]},
        ],
        "wrapper_recipes": [{"wrapper_name": "postJson", "method": "POST", "url_arg_index": 0, "confidence": 0.9}],
        "backend_routes": [
            {"method": "POST", "path": "/api/v1/shop/orders", "handler": "orders.create_order"},
            {"method": "POST", "path": "/api/v1/shop/orders/{order_id}", "handler": "orders.get_order"},
        ],
    })

    assert result["status"] == "ok"
    assert any(edge["to"] == "HTTP POST /api/v1/shop/orders" for edge in result["edges"] if edge["kind"] == "HTTP_CALLS")
    assert any(edge["to"] == "HTTP POST /api/v1/shop/orders/{param}" for edge in result["edges"] if edge["kind"] == "HTTP_CALLS")


def test_frontend_backend_endpoint_bridge_collects_source_facts_and_fastapi_prefixes(tmp_path: Path):
    (tmp_path / "backend" / "app" / "api" / "v1" / "admin").mkdir(parents=True)
    (tmp_path / "frontend" / "src" / "api").mkdir(parents=True)
    (tmp_path / "frontend" / "src" / "constants").mkdir(parents=True)

    (tmp_path / "backend" / "app" / "main.py").write_text(
        """
from fastapi import FastAPI
from app.api import api_router

app = FastAPI()
app.include_router(api_router)
""",
        encoding="utf-8",
    )
    (tmp_path / "backend" / "app" / "api" / "__init__.py").write_text(
        "from .router import router as api_router\n",
        encoding="utf-8",
    )
    (tmp_path / "backend" / "app" / "api" / "router.py").write_text(
        """
from fastapi import APIRouter
from app.api.v1 import router as v1_router

router = APIRouter()
router.include_router(v1_router, prefix="/api")
""",
        encoding="utf-8",
    )
    (tmp_path / "backend" / "app" / "api" / "v1" / "__init__.py").write_text(
        "from .router import router\n",
        encoding="utf-8",
    )
    (tmp_path / "backend" / "app" / "api" / "v1" / "router.py").write_text(
        """
from fastapi import APIRouter
from app.api.v1.admin.routes import router as admin_router

router = APIRouter()
router.include_router(admin_router, prefix="/admin")
""",
        encoding="utf-8",
    )
    (tmp_path / "backend" / "app" / "api" / "v1" / "admin" / "routes.py").write_text(
        """
from fastapi import APIRouter

router = APIRouter(prefix="/accounts")

@router.get("/{account_id}")
def read_admin_account(account_id: str) -> dict[str, str]:
    return {"id": account_id}
""",
        encoding="utf-8",
    )
    (tmp_path / "frontend" / "src" / "constants" / "api.ts").write_text(
        """
export const API_BASE = '/api'
export const ADMIN_SEGMENT = 'admin'
export const ACCOUNT_SEGMENT = 'accounts'
""",
        encoding="utf-8",
    )
    (tmp_path / "frontend" / "src" / "api" / "accounts.ts").write_text(
        """
import { API_BASE, ADMIN_SEGMENT, ACCOUNT_SEGMENT } from '../constants/api'

const accountBase = (): string => `${API_BASE}/${ADMIN_SEGMENT}/${ACCOUNT_SEGMENT}`
const accountPath = (id: string): string => `${accountBase()}/${encodeURIComponent(id)}`

export async function fetchAdminAccount(id: string, transport: typeof fetch = fetch) {
  const url = accountPath(id)
  const response = await transport(url, { headers: { Accept: 'application/json' } })
  return response.json()
}
""",
        encoding="utf-8",
    )

    graph = GraphDocument(metadata={"project_path": str(tmp_path)})
    graph = apply_frontend_backend_endpoint_bridge(graph)

    assert graph.metadata["frontend_backend_endpoint_bridge"]["status"] == "applied"
    assert any(
        edge.kind == "HTTP_CALLS"
        and edge.from_node == "api.accounts.fetchAdminAccount"
        and edge.to_node == "HTTP GET /api/admin/accounts/{param}"
        for edge in graph.edges
    )
    assert any(
        edge.kind == "MATCHES_ENDPOINT"
        and edge.from_node == "HTTP GET /api/admin/accounts/{param}"
        and edge.to_node == "backend.app.api.v1.admin.routes.read_admin_account"
        for edge in graph.edges
    )
