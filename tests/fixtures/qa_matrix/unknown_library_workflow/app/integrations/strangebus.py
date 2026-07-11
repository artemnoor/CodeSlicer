"""Integration surface for the unknown `strangebus` library.

This module intentionally imports `strangebus` as if it were installed from the
`strangebus-sdk` package. The test suite provides a local stub only at test time.
"""

from __future__ import annotations

from typing import Any

from app.services.orders import handle_order_created
import strangebus


# Unknown-library pattern expected to become EVENT_HANDLES after support pack.
strangebus.route("order.created")(handle_order_created)


def publish_order_created(payload: dict[str, Any]) -> None:
    """Unknown-library pattern expected to become EVENT_EMITS."""
    strangebus.emit("order.created", payload)
