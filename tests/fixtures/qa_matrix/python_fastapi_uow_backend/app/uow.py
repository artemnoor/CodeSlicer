"""Unit-of-Work for orders.

Exposes ``orders``, ``users`` and ``billing`` repositories and a
``commit`` / ``rollback`` pair. The same UoW instance is shared across
``OrderService`` and ``PaymentService`` via
:mod:`app.dependencies`.
"""
from __future__ import annotations

from app.repositories.billing import BillingRepository
from app.repositories.orders import OrderRepository
from app.repositories.users import UserRepository


class OrderUnitOfWork:
    def __init__(self) -> None:
        self.orders: OrderRepository = OrderRepository()
        self.users: UserRepository = UserRepository()
        self.billing: BillingRepository = BillingRepository()
        self._committed: bool = False

    # -------------------------------------------------- context manager API
    def __enter__(self) -> "OrderUnitOfWork":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False

    # ----------------------------------------------------------------- commit
    def commit(self) -> bool:
        # In-memory UoW: nothing to flush, but we still record the fact
        # that the transaction was committed. Tests assert on this flag.
        self._committed = True
        return True

    def rollback(self) -> bool:
        self._committed = False
        return True

    @property
    def is_committed(self) -> bool:
        return self._committed
