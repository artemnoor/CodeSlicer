"""Audit service — in-memory event log used by ``OrderService``."""
from __future__ import annotations

from typing import Any, Dict, List


class AuditService:
    def __init__(self) -> None:
        self._events: List[Dict[str, Any]] = []

    def log(self, event: Dict[str, Any]) -> Dict[str, Any]:
        self._events.append(dict(event))
        return event

    def all_events(self) -> List[Dict[str, Any]]:
        return [dict(e) for e in self._events]
