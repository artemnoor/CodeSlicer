"""Reusable resolver fixtures for examples and downstream smoke tests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def checkout_uow_fixture() -> dict[str, Any]:
    """Return a realistic end-to-end checkout/unit-of-work fixture."""

    data: dict[str, Any] = {
        "classes": [
            {
                "id": "services.OrderService",
                "name": "OrderService",
                "methods": [
                    "__init__",
                    "create_order",
                    "complete_checkout",
                    "create_order_through_nested_alias",
                ],
            },
            {
                "id": "repositories.OrderUnitOfWork",
                "name": "OrderUnitOfWork",
                "methods": ["__init__", "commit"],
            },
            {
                "id": "repositories.OrderRepository",
                "name": "OrderRepository",
                "methods": ["save", "find_by_id", "mark_paid"],
            },
            {
                "id": "repositories.LegacyOrderRepository",
                "name": "LegacyOrderRepository",
                "methods": ["mark_paid", "save"],
            },
            {
                "id": "repositories.BillingRepository",
                "name": "BillingRepository",
                "methods": ["save"],
            },
            {
                "id": "services.PaymentService",
                "name": "PaymentService",
                "methods": ["charge_for_order"],
            },
        ],
        "constructor_params": [
            {
                "class": "services.OrderService",
                "param": "repository",
                "type": "repositories.OrderRepository",
                "confidence": 0.95,
                "evidence": ["OrderService.__init__(repository: OrderRepository)"],
            },
            {
                "class": "services.OrderService",
                "param": "uow",
                "type": "repositories.OrderUnitOfWork",
                "confidence": 0.95,
                "evidence": ["OrderService.__init__(uow: OrderUnitOfWork)"],
            },
            {
                "class": "services.OrderService",
                "param": "payment_service",
                "type": "services.PaymentService",
                "confidence": 0.95,
                "evidence": ["OrderService.__init__(payment_service: PaymentService)"],
            },
            {
                "class": "repositories.OrderUnitOfWork",
                "param": "orders",
                "type": "repositories.OrderRepository",
                "confidence": 0.95,
                "evidence": ["OrderUnitOfWork.__init__(orders: OrderRepository)"],
            },
        ],
        "assignments": [
            {
                "scope": "services.OrderService.__init__",
                "target": "self.repository",
                "value": "repository",
                "confidence": 0.95,
                "evidence": ["services.OrderService.__init__: self.repository = repository"],
            },
            {
                "scope": "services.OrderService.__init__",
                "target": "self.uow",
                "value": "uow",
                "confidence": 0.95,
                "evidence": ["services.OrderService.__init__: self.uow = uow"],
            },
            {
                "scope": "services.OrderService.__init__",
                "target": "self.payment_service",
                "value": "payment_service",
                "confidence": 0.95,
                "evidence": ["services.OrderService.__init__: self.payment_service = payment_service"],
            },
            {
                "scope": "repositories.OrderUnitOfWork.__init__",
                "target": "self.orders",
                "value": "orders",
                "confidence": 0.95,
                "evidence": ["repositories.OrderUnitOfWork.__init__: self.orders = orders"],
            },
        ],
        "dict_bindings": [
            {
                "scope": "services.OrderService.__init__",
                "target": "self.nested_alias",
                "entries": {"orders": "repository"},
                "value_types": {"orders": "repositories.OrderRepository"},
                "confidence": 0.82,
                "evidence": ["self.nested_alias = {'orders': repository}"],
            }
        ],
        "calls": [
            {
                "scope": "services.OrderService.create_order",
                "receiver_chain": ["self", "repository"],
                "method": "save",
                "args": ["order"],
            },
            {
                "scope": "services.OrderService.complete_checkout",
                "receiver_chain": ["self", "uow", "orders"],
                "method": "find_by_id",
                "args": ["order_id"],
            },
            {
                "scope": "services.OrderService.complete_checkout",
                "receiver_chain": ["self", "uow", "orders"],
                "method": "mark_paid",
                "args": ["order_id"],
            },
            {
                "scope": "services.OrderService.complete_checkout",
                "receiver_chain": ["self", "uow"],
                "method": "commit",
                "args": [],
            },
            {
                "scope": "services.OrderService.complete_checkout",
                "receiver_chain": ["self", "payment_service"],
                "method": "charge_for_order",
                "args": ["order"],
            },
            {
                "scope": "services.OrderService.create_order_through_nested_alias",
                "receiver_chain": ["self", "nested_alias", {"key": "orders"}],
                "method": "save",
                "args": ["order"],
            },
        ],
        "options": {},
    }
    return deepcopy(data)
