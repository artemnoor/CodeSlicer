"""API-level tests for the orders + users endpoints.

Covers the four required test names:

* ``test_create_order_route_hits_service_chain``
* ``test_checkout_route_uses_uow_and_payment``
* ``test_order_service_create_order_uses_active_repository_not_legacy``
* ``test_users_route_does_not_touch_orders_repository``
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_order_service, get_uow
from app.main import app
from app.repositories.orders import LegacyOrderRepository
from app.services.orders import OrderService


# --------------------------------------------------------------------------- helpers
def _patch_method(obj, attr):
    """Replace ``obj.attr`` with a tracking wrapper. Returns (calls, restore)."""
    calls: list = []
    original = getattr(obj, attr)

    def wrapper(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    setattr(obj, attr, wrapper)

    def restore():
        setattr(obj, attr, original)

    return calls, restore


# --------------------------------------------------------------------------- tests
def test_create_order_route_hits_service_chain():
    """POST /api/v1/shop/orders
        -> app.api.v1.orders.create_order
        -> OrderService.create_order
        -> OrderRepository.save
    """
    client = TestClient(app)

    uow = get_uow()
    order_service: OrderService = get_order_service()

    # Make sure both alias forms point at the *same* active repository.
    order_service.repositories["orders"] = uow.orders
    order_service.nested_alias["orders"] = uow.orders

    save_calls, restore_save = _patch_method(uow.orders, "save")
    try:
        response = client.post(
            "/api/v1/shop/orders",
            json={
                "id": "order-1",
                "user_id": "user-1",
                "items": [{"sku": "ABC", "qty": 2}],
                "total": 100,
            },
        )
    finally:
        restore_save()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == "order-1"
    assert body["status"] == "created"
    assert body["user_id"] == "user-1"

    # The route must have reached OrderRepository.save exactly once.
    assert len(save_calls) == 1
    saved_args, _ = save_calls[0]
    assert saved_args[0]["id"] == "order-1"


def test_checkout_route_uses_uow_and_payment():
    """POST /api/v1/shop/orders/{order_id}/checkout
        -> create_checkout
        -> OrderService.complete_checkout
        -> self.uow.orders.find_by_id
        -> self.uow.orders.mark_paid
        -> PaymentService.charge_for_order
        -> BillingRepository.save_payment_attempt
        -> OrderUnitOfWork.commit
    """
    client = TestClient(app)
    uow = get_uow()
    order_service: OrderService = get_order_service()

    # 1) Create the order via the public route so the UoW has it.
    create_response = client.post(
        "/api/v1/shop/orders",
        json={
            "id": "order-2",
            "user_id": "user-2",
            "items": [{"sku": "XYZ", "qty": 1}],
            "total": 50,
        },
    )
    assert create_response.status_code == 200, create_response.text

    # 2) Patch every node of the expected chain and run checkout.
    find_calls, restore_find = _patch_method(uow.orders, "find_by_id")
    mark_paid_calls, restore_mark_paid = _patch_method(uow.orders, "mark_paid")
    commit_calls, restore_commit = _patch_method(uow, "commit")
    charge_calls, restore_charge = _patch_method(
        order_service.payment_service, "charge_for_order"
    )
    billing_calls, restore_billing = _patch_method(
        uow.billing, "save_payment_attempt"
    )
    try:
        response = client.post("/api/v1/shop/orders/order-2/checkout")
    finally:
        restore_find()
        restore_mark_paid()
        restore_commit()
        restore_charge()
        restore_billing()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["order_id"] == "order-2"
    assert body["status"] == "paid"

    # Every node in the chain must have been called exactly once.
    assert len(find_calls) == 1
    assert find_calls[0][0][0] == "order-2"
    assert len(mark_paid_calls) == 1
    assert mark_paid_calls[0][0][0] == "order-2"
    assert len(charge_calls) == 1
    assert charge_calls[0][0][0]["id"] == "order-2"
    assert len(billing_calls) == 1
    assert billing_calls[0][0][0]["order_id"] == "order-2"
    assert len(commit_calls) == 1


def test_order_service_create_order_uses_active_repository_not_legacy():
    """``OrderService.create_order`` must call ``OrderRepository.save``
    and must NOT call ``LegacyOrderRepository.save``.
    """
    uow = get_uow()
    order_service: OrderService = get_order_service()
    # Force both alias forms to the active repo.
    order_service.repositories["orders"] = uow.orders
    order_service.nested_alias["orders"] = uow.orders

    active_calls, restore_active = _patch_method(uow.orders, "save")

    legacy = LegacyOrderRepository()
    legacy_calls, restore_legacy = _patch_method(legacy, "save")
    try:
        result = order_service.create_order(
            {
                "id": "order-3",
                "user_id": "user-3",
                "items": [],
                "total": 200,
            }
        )
    finally:
        restore_active()
        restore_legacy()

    assert result["id"] == "order-3"
    # Active repo must have been called.
    assert len(active_calls) == 1
    assert active_calls[0][0][0]["id"] == "order-3"
    # Legacy repo must NOT have been called.
    assert len(legacy_calls) == 0


def test_users_route_does_not_touch_orders_repository():
    """``POST /api/v1/users`` must NOT call ``OrderRepository.save``."""
    client = TestClient(app)
    uow = get_uow()

    save_calls, restore_save = _patch_method(uow.orders, "save")
    try:
        response = client.post(
            "/api/v1/users",
            json={"id": "u1", "name": "Alice", "email": "alice@example.com"},
        )
    finally:
        restore_save()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created"] is True
    assert body["user"]["id"] == "u1"
    # The order repository must remain untouched.
    assert len(save_calls) == 0
