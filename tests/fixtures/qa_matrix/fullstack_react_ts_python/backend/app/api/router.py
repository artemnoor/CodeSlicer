"""Top-level API router that all versioned sub-routers attach to."""

from fastapi import APIRouter

api_router = APIRouter()

__all__ = ["api_router"]
