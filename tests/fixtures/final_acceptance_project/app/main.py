from fastapi import FastAPI
from app.routers import router as order_router
import unknown_custom_lib

app = FastAPI()
app.include_router(order_router, prefix="/api")
