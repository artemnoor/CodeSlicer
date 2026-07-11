"""Integration surface for the unknown `magicqueue` library.

This module uses the top-level import exposed by the `magicqueue-client` package.
"""

from __future__ import annotations

from typing import Any

from app.services.orders import handle_order_created
from magicqueue import QueueClient


orders_queue = QueueClient("orders")

# Unknown-library pattern expected to become EVENT_HANDLES after support pack.
orders_queue.subscribe("order.created", handle_order_created)


def publish_order_created(payload: dict[str, Any]) -> None:
    """Unknown-library pattern expected to become EVENT_EMITS."""
    orders_queue.publish("order.created", payload)
