"""Aggregates the v1 routers.

Builds the ``/api/v1/shop`` prefix chain by including the orders router
with ``prefix="/shop"``. The users router is included **without** the
``/shop`` prefix so that users routes live at ``/api/v1/users`` (per the
README's forbidden-false-positive contract).
"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.orders import router as orders_router
from app.api.v1.users import router as users_router

router = APIRouter()
# Prefix chain link #1: /shop  -> orders routes live under /api/v1/shop/orders
router.include_router(orders_router, prefix="/shop")
# Users routes live directly under /api/v1/users (no /shop prefix).
router.include_router(users_router)
