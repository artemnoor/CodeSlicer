"""Workflow containing unknown-library patterns for research workflow tests."""

from __future__ import annotations

import json
import os
import pathlib
from typing import Any

from app.repositories.orders import OrderRepository
from internal_utils_dev import helper
from magicqueue import QueueClient
import strangebus


class OrderWorkflow:
    """Route-facing workflow.

    Expected structural chain:
        OrderWorkflow.create_order
          -> OrderRepository.save
          -> strangebus.emit("order.created", payload)
          -> QueueClient.publish("order.created", payload)
    """

    def __init__(
        self,
        repository: OrderRepository | None = None,
        queue: QueueClient | None = None,
    ) -> None:
        self.repository = repository or OrderRepository()
        self.queue = queue or QueueClient("orders")

    def create_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized_payload = helper.normalize_payload(payload)
        order = self.repository.save(normalized_payload)

        event_payload = {
            "event": "order.created",
            "order": order,
            "source": pathlib.Path(os.getcwd()).name,
            "json_size": len(json.dumps(order, sort_keys=True)),
        }

        strangebus.emit("order.created", event_payload)
        self.queue.publish("order.created", event_payload)

        return order
