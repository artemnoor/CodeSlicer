"""Reusable JSON fixtures for tests and documentation examples."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def fullstack_shop_fixture() -> dict[str, Any]:
    """Return a normalized frontend/backend facts fixture.

    The fixture models:
    OrderCreateForm -> useOrders -> ordersClient functions -> postJson paths ->
    backend FastAPI-like route facts.
    """

    data: dict[str, Any] = {
        "schema_version": "frontend_backend_endpoint_resolver.facts.v1",
        "wrapper_recipes": [
            {"wrapper_name": "postJson", "method": "POST", "url_arg_index": 0, "confidence": 0.88}
        ],
        "modules": [
            {
                "id": "frontend.paths",
                "path": "src/frontend/paths.ts",
                "constants": [
                    {"name": "API_PREFIX", "value": "/api/v1", "exported": True},
                    {"name": "SHOP_PREFIX", "value": "/shop", "exported": True},
                ],
                "functions": [
                    {
                        "id": "frontend.paths.orderPath",
                        "name": "orderPath",
                        "params": [],
                        "exported": True,
                        "returns": {
                            "type": "concat",
                            "parts": [
                                {"type": "ref", "name": "API_PREFIX"},
                                {"type": "ref", "name": "SHOP_PREFIX"},
                                {"type": "literal", "value": "/orders"},
                            ],
                        },
                    },
                    {
                        "id": "frontend.paths.checkoutPath",
                        "name": "checkoutPath",
                        "params": ["id"],
                        "exported": True,
                        "returns": {
                            "type": "template",
                            "parts": [
                                {"type": "call", "name": "orderPath", "args": []},
                                {"type": "literal", "value": "/"},
                                {"type": "ref", "name": "id"},
                                {"type": "literal", "value": "/checkout"},
                            ],
                        },
                    },
                ],
            },
            {
                "id": "frontend.ordersClient",
                "path": "src/frontend/ordersClient.ts",
                "imports": [
                    {"local": "orderPath", "target": "frontend.paths.orderPath"},
                    {"local": "checkoutPath", "target": "frontend.paths.checkoutPath"},
                    {"local": "postJson", "target": "frontend.http.postJson"},
                ],
                "functions": [
                    {
                        "id": "frontend.ordersClient.createOrder",
                        "name": "createOrder",
                        "params": ["payload"],
                        "exported": True,
                        "calls": [
                            {
                                "callee": "postJson",
                                "args": [
                                    {"type": "call", "name": "orderPath", "args": []},
                                    {"type": "ref", "name": "payload"},
                                ],
                            }
                        ],
                    },
                    {
                        "id": "frontend.ordersClient.checkoutOrder",
                        "name": "checkoutOrder",
                        "params": ["id"],
                        "exported": True,
                        "calls": [
                            {
                                "callee": "postJson",
                                "args": [
                                    {"type": "call", "name": "checkoutPath", "args": [{"type": "ref", "name": "id"}]},
                                    {"type": "object", "properties": {}},
                                ],
                            }
                        ],
                    },
                ],
            },
            {
                "id": "frontend.hooks",
                "path": "src/frontend/useOrders.ts",
                "imports": [
                    {"local": "createOrder", "target": "frontend.ordersClient.createOrder"},
                    {"local": "checkoutOrder", "target": "frontend.ordersClient.checkoutOrder"},
                ],
            },
        ],
        "components": [
            {
                "id": "frontend.components.OrderCreateForm",
                "file": "OrderCreateForm.tsx",
                "uses_hooks": ["frontend.hooks.useOrders"],
            }
        ],
        "hooks": [
            {
                "id": "frontend.hooks.useOrders",
                "file": "useOrders.ts",
                "exposes": {
                    "createOrder": "frontend.ordersClient.createOrder",
                    "checkoutOrder": "frontend.ordersClient.checkoutOrder",
                },
            }
        ],
        "backend_routes": [
            {
                "method": "POST",
                "path": "/api/v1/shop/orders",
                "handler": "backend.app.api.orders.create_order",
                "framework": "fastapi",
                "confidence": 0.90,
            },
            {
                "method": "POST",
                "path": "/api/v1/shop/orders/{order_id}/checkout",
                "handler": "backend.app.api.orders.checkout_order",
                "framework": "fastapi",
                "confidence": 0.90,
            },
            {
                "method": "POST",
                "path": "/api/v1/shop/users",
                "handler": "backend.app.api.users.create_user",
                "framework": "fastapi",
                "confidence": 0.90,
            },
        ],
    }
    return deepcopy(data)


def suffix_trap_fixture() -> dict[str, Any]:
    data = fullstack_shop_fixture()
    data["modules"][0]["constants"][0]["value"] = "/legacy/v1"
    data["backend_routes"] = [
        {
            "method": "POST",
            "path": "/api/v1/shop/orders",
            "handler": "backend.app.api.orders.create_order",
            "framework": "fastapi",
            "confidence": 0.90,
        }
    ]
    return data
