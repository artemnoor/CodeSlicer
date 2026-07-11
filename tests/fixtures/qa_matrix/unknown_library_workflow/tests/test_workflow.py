from __future__ import annotations

import strangebus
from magicqueue import QueueClient

from app.services.workflow import OrderWorkflow


def test_create_order_saves_and_publishes_event() -> None:
    strangebus.reset()
    QueueClient.reset()

    workflow = OrderWorkflow()
    order = workflow.create_order({"sku": "coffee-beans", "quantity": 2})

    assert order["id"] == "order-1"
    assert order["payload"]["sku"] == "coffee-beans"

    emitted = strangebus.get_emitted()
    assert len(emitted) == 1
    assert emitted[0]["event"] == "order.created"
    assert emitted[0]["payload"]["order"] == order

    published = QueueClient.get_published()
    assert len(published) == 1
    assert published[0]["channel"] == "orders"
    assert published[0]["event"] == "order.created"
    assert published[0]["payload"]["order"] == order
