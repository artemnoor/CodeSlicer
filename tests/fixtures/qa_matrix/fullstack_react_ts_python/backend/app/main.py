"""FastAPI application entrypoint.

Wires up the API router chain:
    app.include_router(api_router, prefix="/api/v1")
    api_router.include_router(shop_router, prefix="/shop")
    shop_router.include_router(orders_router, prefix="/orders")
"""

from fastapi import FastAPI

from app.api.router import api_router
from app.api.shop import shop_router
from app.api.shop.orders import orders_router
from app.api.shop.users import users_router


def create_app() -> FastAPI:
    """Build and configure the FastAPI application instance."""
    application = FastAPI(title="Impact Analysis Test API")

    # Wire the shop sub-router into the top-level API router.
    shop_router.include_router(orders_router, prefix="/orders")
    shop_router.include_router(users_router, prefix="/users")

    # Wire the shop router into the API router.
    api_router.include_router(shop_router, prefix="/shop")

    # Mount the whole API under /api/v1.
    application.include_router(api_router, prefix="/api/v1")

    @application.get("/health")
    def health() -> dict:
        """Simple health-check endpoint used by tests and operators."""
        return {"status": "ok"}

    return application


app = create_app()
