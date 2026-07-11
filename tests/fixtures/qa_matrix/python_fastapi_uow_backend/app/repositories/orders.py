"""Order, user and billing repositories (in-memory).

The ``orders`` module deliberately exposes **two** classes with a ``save``
method: the active ``OrderRepository`` and a ``LegacyOrderRepository`` that
is kept around for backward compatibility but **must never be called** by
``OrderService``. This pair is one of the impact-analysis traps — a static
analyzer that only looks at the symbol ``OrderRepository.save`` should not
be fooled into thinking ``LegacyOrderRepository.save`` participates in the
``create_order`` chain.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


class OrderRepository:
    """Active repository used by ``OrderUnitOfWork.orders``."""

    def __init__(self) -> None:
        self._storage: Dict[str, Dict[str, Any]] = {}

    def save(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """Persist (or update) an order keyed by ``order["id"]``."""
        order_id = order["id"]
        # Always store a fresh copy so callers cannot mutate stored state.
        self._storage[order_id] = dict(order)
        return self._storage[order_id]

    def find_by_id(self, order_id: str) -> Optional[Dict[str, Any]]:
        stored = self._storage.get(order_id)
        return dict(stored) if stored is not None else None

    def mark_paid(self, order_id: str) -> Optional[Dict[str, Any]]:
        order = self._storage.get(order_id)
        if order is None:
            return None
        order["status"] = "paid"
        self._storage[order_id] = order
        return dict(order)

    def all(self) -> List[Dict[str, Any]]:
        return [dict(o) for o in self._storage.values()]


class LegacyOrderRepository:
    """Deprecated repository.

    Kept in the codebase for historical reasons. ``OrderService`` MUST NOT
    use this class — it exists purely as an impact-analysis trap. A
    high-quality analyzer should be able to prove that
    ``LegacyOrderRepository.save`` is never reachable from
    ``POST /api/v1/shop/orders``.
    """

    def __init__(self) -> None:
        self._legacy_storage: List[Dict[str, Any]] = []

    def save(self, order: Dict[str, Any]) -> Dict[str, Any]:
        self._legacy_storage.append(order)
        return order

    def all_legacy(self) -> List[Dict[str, Any]]:
        return list(self._legacy_storage)
