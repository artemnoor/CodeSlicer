from __future__ import annotations

from typing import Iterable, List


class DiagnosticBag:
    """Deterministic string diagnostics with de-duplication."""

    def __init__(self, initial: Iterable[str] = ()) -> None:
        self._items: List[str] = []
        self.extend(initial)

    def add(self, message: str) -> None:
        if message and message not in self._items:
            self._items.append(message)

    def extend(self, messages: Iterable[str]) -> None:
        for message in messages:
            self.add(message)

    def to_list(self) -> List[str]:
        return sorted(self._items)
