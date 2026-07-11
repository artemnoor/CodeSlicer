"""User repository (in-memory).

The user-facing routes live in :mod:`app.api.v1.users` and intentionally
do **not** import or call anything from :mod:`app.repositories.orders`.
This separation is what makes ``POST /api/v1/users`` an expected
*forbidden false positive* for the OrderRepository.save impact chain.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


class UserRepository:
    def __init__(self) -> None:
        self._storage: Dict[str, Dict[str, Any]] = {}

    def save(self, user: Dict[str, Any]) -> Dict[str, Any]:
        self._storage[user["id"]] = dict(user)
        return self._storage[user["id"]]

    def find_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        stored = self._storage.get(user_id)
        return dict(stored) if stored is not None else None
