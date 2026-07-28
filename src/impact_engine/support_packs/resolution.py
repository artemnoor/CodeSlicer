"""Neutral support-pack resolution facade."""
from __future__ import annotations

from .compatibility_loader import load_legacy_resolution


def apply_support_pack_rules(*args, **kwargs):
    """Delegate legacy JSON rules through the isolated compatibility boundary."""
    return load_legacy_resolution().apply_support_pack_rules(*args, **kwargs)


__all__ = ["apply_support_pack_rules"]
