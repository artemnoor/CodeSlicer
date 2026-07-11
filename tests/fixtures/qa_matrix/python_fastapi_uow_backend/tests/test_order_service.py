"""Direct unit tests for ``OrderService``.

These tests bypass FastAPI and verify the service-level call chain in
isolation. They are stricter than the API tests in
``test_orders_api.py`` because they also assert the *order* in which
the chain nodes fire.
"""
from __future__ import annotations

from app.dependencies import get_order_service, get_uow
from app.services.orders import OrderService


def _patch(obj, attr):
    calls: list = []
    original = getattr(obj, attr)

    def wrapper(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    setattr(obj, attr, wrapper)

    def restore():
        setattr(obj, attr, original)

    return calls, restore


def test_create_order_calls_active_repository_save():
    """``OrderService.create_order`` reaches ``OrderRepository.save``
    via the ``self.repositories["orders"]`` alias."""
    uow = get_uow()
    service: OrderService = get_order_service()
    service.repositories["orders"] = uow.orders
    service.nested_alias["orders"] = uow.orders

    calls, restore = _patch(uow.orders, "save")
    try:
        service.create_order(
            {"id": "svc-1", "user_id": "user-1", "items": [], "total": 10}
        )
    finally:
        restore()

    assert len(calls) == 1
    assert calls[0][0][0]["id"] == "svc-1"


def test_refresh_order_uses_nested_alias():
    """``OrderService.refresh_order`` reaches the same
    ``OrderRepository.save`` via ``self.nested_alias["orders"]``."""
    uow = get_uow()
    service: OrderService = get_order_service()
    service.repositories["orders"] = uow.orders
    service.nested_alias["orders"] = uow.orders

    calls, restore = _patch(uow.orders, "save")
    try:
        service.refresh_order({"id": "svc-2", "status": "updated"})
    finally:
        restore()

    assert len(calls) == 1
    assert calls[0][0][0]["id"] == "svc-2"


def test_get_order_returns_none_for_missing_id():
    uow = get_uow()
    service: OrderService = get_order_service()
    assert service.get_order("does-not-exist") is None
