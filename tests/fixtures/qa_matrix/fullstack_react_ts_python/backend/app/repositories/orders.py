"""Repository layer for orders.

The repository is the ONLY place that owns order persistence. Impact analysis
should treat `OrderRepository.save` as the canonical write entrypoint.
"""

from __future__ import annotations

import copy


class OrderRepository:
    """In-memory order repository, hermetic for tests."""

    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    def save(self, order: dict) -> dict:
        """Persist an order and return a deep copy to avoid aliasing bugs."""
        self._store[order["id"]] = copy.deepcopy(order)
        return copy.deepcopy(order)

    def get(self, order_id: str) -> dict | None:
        """Return a copy of the stored order, or None if it does not exist."""
        order = self._store.get(order_id)
        return copy.deepcopy(order) if order is not None else None


# Trap: similar name that should NOT be linked to OrderRepository.save by
# impact-analysis tools. It is intentionally a free function with no caller
# in the production code path.
def save_order_draft(draft: dict) -> dict:
    """Pretend to save a draft order.

    This function exists only to trick naive symbol matchers that match on
    the `save` substring. It must NOT be linked to OrderRepository.save.
    """
    draft.setdefault("id", "draft_unknown")
    draft["status"] = "draft"
    return draft
