"""Test-only stub for the unknown `magicqueue` package."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class QueueClient:
    _published: list[dict[str, Any]] = []
    _subscriptions: list[dict[str, Any]] = []

    def __init__(self, channel: str) -> None:
        self.channel = channel

    def publish(self, event_name: str, payload: dict[str, Any]) -> None:
        self.__class__._published.append(
            {"channel": self.channel, "event": event_name, "payload": payload}
        )

    def subscribe(
        self,
        event_name: str,
        handler: Callable[[dict[str, Any]], None],
    ) -> Callable[[dict[str, Any]], None]:
        self.__class__._subscriptions.append(
            {"channel": self.channel, "event": event_name, "handler": handler}
        )
        return handler

    @classmethod
    def get_published(cls) -> list[dict[str, Any]]:
        return list(cls._published)

    @classmethod
    def get_subscriptions(cls) -> list[dict[str, Any]]:
        return list(cls._subscriptions)

    @classmethod
    def reset(cls) -> None:
        cls._published.clear()
        cls._subscriptions.clear()
