"""Order event handlers.

These functions are intentionally simple. They exist so library-specific
patterns can point to concrete local handler nodes.
"""

from __future__ import annotations

from typing import Any


HANDLED_EVENTS: list[dict[str, Any]] = []


def handle_order_created(payload: dict[str, Any]) -> None:
    """Local handler for the order.created event."""
    HANDLED_EVENTS.append(payload)


def reset_handled_events() -> None:
    HANDLED_EVENTS.clear()
