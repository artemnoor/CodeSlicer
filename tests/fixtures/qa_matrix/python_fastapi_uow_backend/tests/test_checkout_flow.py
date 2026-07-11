"""End-to-end checkout-flow tests.

These tests verify that the full checkout chain fires in the expected
order and that ``OrderUnitOfWork.commit`` is the final step. They
exercise ``OrderService.complete_checkout`` directly (without going
through FastAPI) to keep the assertions tight.
"""
from __future__ import annotations

import pytest

from app.dependencies import get_order_service, get_uow
from app.services.orders import OrderService


def _patch(obj, attr, log, label):
    original = getattr(obj, attr)

    def wrapper(*args, **kwargs):
        log.append(label)
        return original(*args, **kwargs)

    setattr(obj, attr, wrapper)

    def restore():
        setattr(obj, attr, original)

    return restore


def test_checkout_flow_full_chain_order():
    """Verify call order:
        find_by_id
        -> charge_for_order
        -> save_payment_attempt    (inside charge_for_order)
        -> mark_paid
        -> commit
    """
    uow = get_uow()
    service: OrderService = get_order_service()

    # Seed an order using the public service method.
    service.create_order(
        {"id": "flow-1", "user_id": "user-1", "items": [{"sku": "K", "qty": 3}], "total": 75}
    )

    log: list[str] = []
    restores = [
        _patch(uow.orders, "find_by_id", log, "find_by_id"),
        _patch(uow.orders, "mark_paid", log, "mark_paid"),
        _patch(uow, "commit", log, "commit"),
        _patch(service.payment_service, "charge_for_order", log, "charge_for_order"),
        _patch(uow.billing, "save_payment_attempt", log, "save_payment_attempt"),
    ]
    try:
        result = service.complete_checkout("flow-1")
    finally:
        for restore in restores:
            restore()

    assert result["status"] == "paid"
    assert result["order_id"] == "flow-1"

    # Every node must have fired.
    for node in (
        "find_by_id",
        "mark_paid",
        "charge_for_order",
        "save_payment_attempt",
        "commit",
    ):
        assert node in log, f"missing chain node: {node}"

    # Order constraints.
    assert log.index("find_by_id") < log.index("charge_for_order")
    assert log.index("charge_for_order") < log.index("save_payment_attempt")
    assert log.index("save_payment_attempt") < log.index("mark_paid")
    assert log.index("mark_paid") < log.index("commit")
    # Commit must be the LAST event.
    assert log[-1] == "commit"


def test_checkout_flow_raises_on_missing_order():
    service: OrderService = get_order_service()
    with pytest.raises(ValueError):
        service.complete_checkout("nonexistent")


def test_checkout_flow_marks_order_paid_in_storage():
    """After ``complete_checkout`` the stored order must have status=paid."""
    uow = get_uow()
    service: OrderService = get_order_service()
    service.create_order(
        {"id": "flow-2", "user_id": "user-2", "items": [], "total": 0}
    )
    service.complete_checkout("flow-2")

    stored = uow.orders.find_by_id("flow-2")
    assert stored is not None
    assert stored["status"] == "paid"


def test_checkout_flow_records_payment_attempt():
    """``BillingRepository.save_payment_attempt`` must record exactly one
    attempt per checkout."""
    uow = get_uow()
    service: OrderService = get_order_service()
    service.create_order(
        {"id": "flow-3", "user_id": "user-3", "items": [], "total": 42}
    )
    service.complete_checkout("flow-3")

    attempts = uow.billing.all_attempts()
    assert len(attempts) == 1
    assert attempts[0]["order_id"] == "flow-3"
    assert attempts[0]["amount"] == 42
    assert attempts[0]["status"] == "succeeded"
