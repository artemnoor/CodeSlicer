"""Billing repository (in-memory).

Stores payment attempts. Used by ``PaymentService.charge_for_order``
during the checkout flow.
"""
from __future__ import annotations

from typing import Any, Dict, List


class BillingRepository:
    def __init__(self) -> None:
        self._attempts: List[Dict[str, Any]] = []

    def save_payment_attempt(self, attempt: Dict[str, Any]) -> Dict[str, Any]:
        self._attempts.append(dict(attempt))
        return attempt

    def all_attempts(self) -> List[Dict[str, Any]]:
        return [dict(a) for a in self._attempts]
