"""FastAPI application factory.

Builds the prefix chain::

    /api                       (this module, include_router prefix)
      └── /v1                  (app.api.router, include_router prefix)
            ├── /shop          (app.api.v1.router, include_router prefix)
            │     └── /orders  (app.api.v1.orders, APIRouter prefix)
            └── /users         (app.api.v1.users, APIRouter prefix)
"""
from __future__ import annotations

from fastapi import FastAPI

from app.api import router as api_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Impact-Analysis Test Backend",
        description=(
            "A small FastAPI service designed to exercise impact-analysis "
            "tools: dict-style repository aliases, an unused legacy "
            "repository, router-variable collisions and multi-level "
            "include_router prefix chains."
        ),
        version="0.1.0",
    )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    # Prefix chain link #0: /api
    app.include_router(api_router, prefix="/api")
    return app


app = create_app()
