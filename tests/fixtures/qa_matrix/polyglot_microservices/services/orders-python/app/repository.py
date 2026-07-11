from __future__ import annotations


class OrderRepository:
    """Repository intentionally named with a lowercase save method.

    The analyzer should link OrderService.create_order -> OrderRepository.save
    inside Python, but must not confuse this with Go Save/SaveInvoice methods.
    """

    def __init__(self) -> None:
        self._orders: list[dict] = []

    def save(self, order: dict) -> dict:
        saved = {**order, "persisted": True}
        self._orders.append(saved)
        return saved

    def save_invoice(self, invoice: dict) -> dict:
        """Trap: similar to billing SaveInvoice, but unrelated to order creation."""
        return {**invoice, "ignored_trap": True}
