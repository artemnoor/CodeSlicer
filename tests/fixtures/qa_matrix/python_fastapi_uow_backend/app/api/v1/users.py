"""``/api/v1/users`` routes.

This module declares its own ``router = APIRouter()`` — the same variable
name used by :mod:`app.api.v1.orders`. That is the **router-variable
collision** trap: a naive static analyzer that resolves routers by name
alone might wrongly conclude that the orders chain and the users chain
share state.

Crucially, **no** handler here imports or calls anything from
:mod:`app.repositories.orders`. So a change to ``OrderRepository.save``
must NOT propagate to ``POST /api/v1/users``.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

# NOTE: same variable name as in app/api/v1/orders.py — intentional
# router-variable collision trap.
router = APIRouter(prefix="/users", tags=["users"])


@router.post("")
def create_user(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Create a user. Does NOT touch OrderRepository.save."""
    user = {
        "id": payload.get("id", "anonymous"),
        "name": payload.get("name", ""),
        "email": payload.get("email", ""),
    }
    return {"created": True, "user": user}


@router.get("/{user_id}")
def get_user(user_id: str) -> Dict[str, Any]:
    """Return a stub user. Does NOT touch OrderRepository.save."""
    return {"id": user_id, "name": "anonymous"}
