"""Shop sub-package exposing the shop-level router."""

from fastapi import APIRouter

shop_router = APIRouter()

__all__ = ["shop_router"]
