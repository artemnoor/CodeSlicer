"""Test-only stub for the unknown `strangebus` package."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_EMITTED: list[dict[str, Any]] = []
_ROUTES: dict[str, Callable[[dict[str, Any]], None]] = {}


def route(event_name: str):
    def decorator(handler: Callable[[dict[str, Any]], None]):
        _ROUTES[event_name] = handler
        return handler

    return decorator


def emit(event_name: str, payload: dict[str, Any]) -> None:
    _EMITTED.append({"event": event_name, "payload": payload})


def get_emitted() -> list[dict[str, Any]]:
    return list(_EMITTED)


def get_routes() -> dict[str, Callable[[dict[str, Any]], None]]:
    return dict(_ROUTES)


def reset() -> None:
    _EMITTED.clear()
    _ROUTES.clear()
