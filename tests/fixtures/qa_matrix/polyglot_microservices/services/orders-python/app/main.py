from __future__ import annotations

from fastapi import FastAPI

from .api import router


def create_app() -> FastAPI:
    app = FastAPI(title="Orders Python Fixture")
    app.include_router(router, prefix="/api")
    return app


app = create_app()
