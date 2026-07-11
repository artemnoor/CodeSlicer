"""Test-only stub for dev/internal helper package."""

from __future__ import annotations

from typing import Any


class helper:
    @staticmethod
    def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
        return dict(payload)
