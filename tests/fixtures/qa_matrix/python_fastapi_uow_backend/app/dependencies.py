"""FastAPI dependency providers.

We deliberately avoid ``functools.lru_cache`` so that tests can call
``reset_dependencies()`` to obtain a fresh object graph. The providers
return module-level singletons that are re-created on reset.
"""
from __future__ import annotations

from typing import Optional

from app.services.audit import AuditService
from app.services.orders import OrderService
from app.services.payments import PaymentService
from app.uow import OrderUnitOfWork

# Module-level singletons. They are created lazily on first access and
# torn down by ``reset_dependencies`` (used heavily by tests).
_uow: Optional[OrderUnitOfWork] = None
_payment_service: Optional[PaymentService] = None
_audit_service: Optional[AuditService] = None
_order_service: Optional[OrderService] = None


def get_uow() -> OrderUnitOfWork:
    global _uow
    if _uow is None:
        _uow = OrderUnitOfWork()
    return _uow


def get_payment_service() -> PaymentService:
    global _payment_service
    if _payment_service is None:
        _payment_service = PaymentService(get_uow().billing)
    return _payment_service


def get_audit_service() -> AuditService:
    global _audit_service
    if _audit_service is None:
        _audit_service = AuditService()
    return _audit_service


def get_order_service() -> OrderService:
    global _order_service
    if _order_service is None:
        _order_service = OrderService(
            uow=get_uow(),
            payment_service=get_payment_service(),
            audit_service=get_audit_service(),
        )
    return _order_service


def reset_dependencies() -> None:
    """Tear down every cached dependency.

    Called by the pytest ``autouse`` fixture in each test module so that
    tests do not leak state into each other.
    """
    global _uow, _payment_service, _audit_service, _order_service
    _uow = None
    _payment_service = None
    _audit_service = None
    _order_service = None
