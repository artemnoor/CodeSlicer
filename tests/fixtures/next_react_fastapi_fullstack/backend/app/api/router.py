from fastapi import APIRouter

from app.api.shop import router as shop_router

router = APIRouter()
router.include_router(shop_router, prefix="/shop")
