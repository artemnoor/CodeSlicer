"""HTTP routes for shop users.

NOTE: This module is intentionally NOT connected to OrderRepository in any way.
It exists as a trap for impact-analysis tools to verify that user-related
changes do not propagate into the orders repository chain.
"""

from fastapi import APIRouter, status
from pydantic import BaseModel, Field


users_router = APIRouter()


class UserCreateIn(BaseModel):
    """Payload accepted by POST /api/v1/shop/users."""

    name: str = Field(..., min_length=1)
    email: str = Field(..., min_length=3)


class UserOut(BaseModel):
    """User representation returned to the client."""

    id: str
    name: str
    email: str


# In-memory store to keep tests hermetic. Deliberately NOT shared with orders.
_USER_STORE: dict[str, dict] = {}


@users_router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreateIn) -> UserOut:
    """Create a new user. Unrelated to OrderRepository.save."""
    user_id = f"usr_{len(_USER_STORE) + 1}"
    user = {"id": user_id, "name": payload.name, "email": payload.email}
    _USER_STORE[user_id] = user
    return UserOut(**user)
