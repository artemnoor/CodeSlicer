"""Regression E2E for a unique frontend-to-backend value flow.

The fixture deliberately derives the endpoint from separate frontend constants.
The assertion therefore proves that the canonical graph preserves the resolved
unique value all the way through the FastAPI handler and repository call.
"""

from pathlib import Path
import shutil

from impact_engine.analysis.pipeline import analyze_project_core


FIXTURE = Path(__file__).parent / "fixtures" / "next_react_fastapi_fullstack"
ENDPOINT = "/api/v1/shop/orders"
HANDLER = "backend.app.api.shop.create_order"
REPOSITORY_SAVE = "backend.app.repositories.orders.OrderRepository.save"


def _fresh_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "fullstack"
    shutil.copytree(FIXTURE, target, ignore=shutil.ignore_patterns(".impact_engine", "__pycache__"))
    return target


def test_unique_order_value_reaches_fastapi_handler_and_repository_e2e(tmp_path):
    graph = analyze_project_core(str(_fresh_fixture(tmp_path)))["graph"]
    edges = graph["edges"]

    frontend_to_handler = next(
        edge for edge in edges
        if edge["kind"] == "MATCHES_ENDPOINT"
        and edge["from"] == "createOrder"
        and edge["to"] == HANDLER
    )
    assert frontend_to_handler["properties"]["status"] == "confirmed"
    assert any(ENDPOINT in item.get("description", "") for item in frontend_to_handler["evidence"])

    route_to_handler = next(
        edge for edge in edges
        if edge["kind"] == "ROUTE_HANDLES"
        and edge["from"] == f"HTTP POST {ENDPOINT}"
        and edge["to"] == HANDLER
    )
    assert route_to_handler["properties"]["status"] == "confirmed"

    assert any(
        edge["kind"] == "CALLS"
        and edge["from"] == "backend.app.services.orders.OrderService.create_order"
        and edge["to"] == REPOSITORY_SAVE
        and edge["properties"]["status"] == "confirmed"
        for edge in edges
    )
