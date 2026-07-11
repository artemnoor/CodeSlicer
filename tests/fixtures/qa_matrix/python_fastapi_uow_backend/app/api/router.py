"""Aggregates the top-level API router under ``/api``.

``app.main`` includes this router with ``prefix="/api"``; this module in
turn includes the v1 router with ``prefix="/v1"`` — building the
multi-level prefix chain ``/api/v1/...``.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import router as v1_router

router = APIRouter()
# Prefix chain link #2: /v1
router.include_router(v1_router, prefix="/v1")
